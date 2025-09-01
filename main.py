import io
import time
import typing
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from typing import List

import httpx
import os

from PIL import Image
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, UploadFile, Header
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, delete
from starlette import status

from database import get_session_user, User, connection, random_session_token, sessions, Base, engine, Product, \
    ProductImage, UserSession
from languages import SUPPORTED_LANGUAGES, TRANSLATIONS
from product_categories import PRODUCT_CATEGORIES, CATEGORIES, MATERIALS, COLORS

load_dotenv()

# Poberemo skrivne vrednosti iz okoljskih spremenljivk
MICROSOFT_CLIENT_ID = os.environ["MICROSOFT_CLIENT_ID"]
MICROSOFT_CLIENT_SECRET = os.environ["MICROSOFT_CLIENT_SECRET"]
SCOPE = "https://graph.microsoft.com/User.Read https://graph.microsoft.com/User.ReadBasic.All"

ALLOWED_PRODUCT_STATES = [
    -1, # Neznana
    50, # Slaba
    75, # Srednja
    100, # Dobra
    200, # Zelo dobra
    300, # Odlična
]

def translate(text_identifier: str, lang: str) -> str:
    if lang is None or lang == "" or lang not in SUPPORTED_LANGUAGES:
        lang = "sl"
    tr = TRANSLATIONS.get(text_identifier)
    if tr is None:
        return text_identifier
    if tr.get(lang) is None:
        if tr.get("sl") is None:
            return text_identifier
        return tr.get("sl")
    return tr.get(lang)

def translate_number(text_identifier: str, number: int, lang: str) -> str:
    if number == 1:
        text_identifier += "_singular"
    elif number == 2:
        text_identifier += "_dual"
    elif number == 3 or number == 4:
        text_identifier += "_three_four"
    else:
        text_identifier += "_plural"
    return translate(text_identifier, lang)

def app_context(request: Request) -> typing.Dict[str, typing.Any]:
    lang = request.cookies.get("lang")
    if lang is None or lang == "" or lang not in SUPPORTED_LANGUAGES:
        lang = "sl"
    user = get_session_user(request.cookies.get("session"))
    name = f"{user.user.first_name} {user.user.surname}" if user is not None else None
    is_admin = False if user is None else user.user.is_admin
    is_teacher = False if user is None else user.user.is_teacher
    return {
        "PRODUCT_CATEGORIES": PRODUCT_CATEGORIES,
        "lang": lang,
        "CATEGORIES": CATEGORIES,
        "COLORS": COLORS,
        "MATERIALS": MATERIALS,
        "name": name,
        "is_admin": is_admin,
        "is_teacher": is_teacher,
    }

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Executed on startup
    async with engine.begin() as conn:
        print("Creating database!")
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Executed after end

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="static")
templates = Jinja2Templates(directory="templates", context_processors=[app_context])
templates.env.filters["translate"] = translate
templates.env.filters["translate_number"] = translate_number

def sort_by_creation_date(e: Product):
    return e.published_at

def sort_by_modified_date(e: Product):
    return e.last_edited_at

def sort_by_name(e: Product):
    return e.name

def sort_by_size(e: Product):
    if e.size == "XXS":
        return "0"
    elif e.size == "XS":
        return "1"
    elif e.size == "S":
        return "2"
    elif e.size == "M":
        return "3"
    elif e.size == "L":
        return "4"
    elif e.size == "XL":
        return "5"
    elif e.size == "XXL":
        return "6"
    return e.size

@app.get("/")
async def home(
        request: Request,
        login_success: bool | None = None,
        sort: str = "",
        active: bool = False,
        archived: bool = False,
        draft: bool = False,
        hat: bool = False,
        sunglasses: bool = False,
        men_sweater: bool = False,
        women_sweater: bool = False,
        unisex_sweater: bool = False,
        men_shirts: bool = False,
        women_shirts: bool = False,
        men_jacket: bool = False,
        women_jacket: bool = False,
        men_pants: bool = False,
        women_pants: bool = False,
        women_dress: bool = False,
        women_skirts: bool = False,
        men_shoes: bool = False,
        women_shoes: bool = False,
        accessories: bool = False,
        teacher: bool = False,
        my_reservations: bool = False,
):
    user = get_session_user(request.cookies.get("session"))
    name = f"{user.user.first_name} {user.user.surname}" if user is not None else None
    is_admin = False if user is None else user.user.is_admin
    is_teacher = False if user is None else user.user.is_teacher

    # Če je vse uncheckano, checkamo zadeve
    if not active and not archived and not draft:
        active = True
        archived = False
        draft = True
    if (
            not hat and
            not sunglasses and
            not men_sweater and
            not women_sweater and
            not unisex_sweater and
            not men_shirts and
            not women_shirts and
            not men_jacket and
            not women_jacket and
            not men_pants and
            not women_pants and
            not women_skirts and
            not women_dress and
            not men_shoes and
            not women_shoes and
            not accessories):
        hat = True
        sunglasses = True
        men_sweater = True
        women_sweater = True
        unisex_sweater = True
        men_shirts = True
        women_shirts = True
        men_jacket = True
        women_jacket = True
        men_pants = True
        women_pants = True
        women_skirts = True
        women_dress = True
        men_shoes = True
        women_shoes = True
        accessories = True

    async with connection.begin() as session:
        if is_admin:
            products = (await session.execute(select(Product).filter_by())).all()
        else:
            products = (await session.execute(select(Product).filter_by(
                draft=False,
                archived=False,
                limit_to_teachers=is_teacher,
            ))).all()
        products: List[Product] = [product[0] for product in products]
        products_filtered = []
        products_filtered2 = []
        for product in products:
            if teacher and not product.teacher:
                continue
            if not is_admin and (product.reserved_by_id is not None and product.reserved_by_id != "" and product.reserved_by_id != (user.user.user_id if user is not None else "")):
                continue
            if my_reservations:
                if product.reserved_by_id == (user.user.user_id if user is not None else ""):
                    products_filtered.append(product)
                continue
            if active and not product.archived and not product.draft:
                products_filtered.append(product)
            elif archived and product.archived:
                products_filtered.append(product)
            elif draft and product.draft:
                products_filtered.append(product)
        for product in products_filtered:
            if hat and product.category == "hat":
                products_filtered2.append(product)
            elif sunglasses and product.category == "sunglasses":
                products_filtered2.append(product)
            elif men_sweater and product.category == "men-sweater":
                products_filtered2.append(product)
            elif women_sweater and product.category == "women-sweater":
                products_filtered2.append(product)
            elif unisex_sweater and product.category == "unisex-sweater":
                products_filtered2.append(product)
            elif men_shirts and product.category == "men-shirts":
                products_filtered2.append(product)
            elif women_shirts and product.category == "women-shirts":
                products_filtered2.append(product)
            elif men_jacket and product.category == "men-jacket":
                products_filtered2.append(product)
            elif women_jacket and product.category == "women-jacket":
                products_filtered2.append(product)
            elif men_pants and product.category == "men-pants":
                products_filtered2.append(product)
            elif women_pants and product.category == "women-pants":
                products_filtered2.append(product)
            elif women_skirts and product.category == "women-skirts":
                products_filtered2.append(product)
            elif women_dress and product.category == "women-dress":
                products_filtered2.append(product)
            elif men_shoes and product.category == "men-shoes":
                products_filtered2.append(product)
            elif women_shoes and product.category == "women-shoes":
                products_filtered2.append(product)
            elif accessories and product.category == "accessories":
                products_filtered2.append(product)
        if sort == "":
            products_filtered2.sort(key=sort_by_modified_date, reverse=True)
        elif sort == "last-changed-asc":
            products_filtered2.sort(key=sort_by_modified_date)
        elif sort == "created-desc":
            products_filtered2.sort(key=sort_by_creation_date, reverse=True)
        elif sort == "created-asc":
            products_filtered2.sort(key=sort_by_creation_date)
        elif sort == "alphabet-asc":
            products_filtered2.sort(key=sort_by_name)
        elif sort == "alphabet-desc":
            products_filtered2.sort(key=sort_by_name, reverse=True)
        elif sort == "size-asc":
            products_filtered2.sort(key=sort_by_size)
        elif sort == "size-desc":
            products_filtered2.sort(key=sort_by_size, reverse=True)
    return templates.TemplateResponse(
        request=request, name="home.jinja", context={
            "login_success": login_success,
            "name": name,
            "is_admin": is_admin,
            "is_teacher": is_teacher,
            "products": products_filtered2,
            "sorting_method": sort,
            "filters": {
                "filter_active": active,
                "filter_archived": archived,
                "filter_draft": draft,
                "filter_hat": hat,
                "filter_sunglasses": sunglasses,
                "filter_men_sweater": men_sweater,
                "filter_women_sweater": women_sweater,
                "filter_unisex_sweater": unisex_sweater,
                "filter_men_shirts": men_shirts,
                "filter_women_shirts": women_shirts,
                "filter_men_jacket": men_jacket,
                "filter_women_jacket": women_jacket,
                "filter_men_pants": men_pants,
                "filter_women_pants": women_pants,
                "filter_women_skirts": women_skirts,
                "filter_women_dress": women_dress,
                "filter_men_shoes": men_shoes,
                "filter_women_shoes": women_shoes,
                "filter_accessories": accessories,
                "filter_teacher": teacher,
                "filter_my_reservations": my_reservations,
            },
            "time": int(time.time()),
        }
    )

@app.post("/")
async def home_post(
        sorting_method: str = Form(""),
        active: bool = Form(False),
        archived: bool = Form(False),
        draft: bool = Form(False),
        hat: bool = Form(False),
        sunglasses: bool = Form(False),
        men_sweater: bool = Form(False),
        women_sweater: bool = Form(False),
        unisex_sweater: bool = Form(False),
        men_shirts: bool = Form(False),
        women_shirts: bool = Form(False),
        men_jacket: bool = Form(False),
        women_jacket: bool = Form(False),
        men_pants: bool = Form(False),
        women_pants: bool = Form(False),
        women_skirts: bool = Form(False),
        women_dress: bool = Form(False),
        men_shoes: bool = Form(False),
        women_shoes: bool = Form(False),
        accessories: bool = Form(False),
        teacher: bool = Form(False),
        my_reservations: bool = Form(False),
):
    encode: dict[str, str | bool] = {
        "sort": sorting_method,
    }
    if active:
        encode["active"] = True
    if archived:
        encode["archived"] = True
    if draft:
        encode["draft"] = True
    if accessories:
        encode["accessories"] = True
    if hat:
        encode["hat"] = True
    if sunglasses:
        encode["sunglasses"] = True
    if men_sweater:
        encode["men_sweater"] = True
    if women_sweater:
        encode["women_sweater"] = True
    if unisex_sweater:
        encode["unisex_sweater"] = True
    if men_shirts:
        encode["men_shirts"] = True
    if women_shirts:
        encode["women_shirts"] = True
    if men_jacket:
        encode["men_jacket"] = True
    if women_jacket:
        encode["women_jacket"] = True
    if men_pants:
        encode["men_pants"] = True
    if women_pants:
        encode["women_pants"] = True
    if women_skirts:
        encode["women_skirts"] = True
    if women_dress:
        encode["women_dress"] = True
    if men_shoes:
        encode["men_shoes"] = True
    if women_shoes:
        encode["women_shoes"] = True
    if teacher:
        encode["teacher"] = True
    if my_reservations:
        encode["my_reservations"] = True
    return RedirectResponse(app.url_path_for("home") + f"?{urllib.parse.urlencode(encode)}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/about")
async def about_project(request: Request):
    user = get_session_user(request.cookies.get("session"))
    name = f"{user.user.first_name} {user.user.surname}" if user is not None else None
    is_admin = False if user is None else user.user.is_admin
    return templates.TemplateResponse(
        request=request, name="about.jinja", context={"name": name, "is_admin": is_admin}
    )

@app.get("/item/{item_id}")
async def item_details(request: Request, item_id: str):
    user = get_session_user(request.cookies.get("session"))
    name = f"{user.user.first_name} {user.user.surname}" if user is not None else None
    is_admin = False if user is None else user.user.is_admin
    is_teacher = False if user is None else user.user.is_teacher
    async with connection.begin() as session:
        product = (await session.execute(select(Product).filter_by(product_id=item_id))).one_or_none()
        if product is None:
            return RedirectResponse(app.url_path_for("home"))
        product = product[0]
        if product is None:
            return RedirectResponse(app.url_path_for("home"))
        if product.limit_to_teachers and not (is_admin or is_teacher):
            return RedirectResponse(app.url_path_for("home"))
        if (product.draft or product.archived) and not is_admin:
            return RedirectResponse(app.url_path_for("home"))
        product_images = (await session.execute(select(ProductImage).filter_by(product_id=item_id).order_by(ProductImage.position))).all()
        product_images = [product_image[0] for product_image in product_images]

        reserver = (await session.execute(select(User).filter_by(user_id=product.reserved_by_id))).one_or_none()
        if reserver is not None:
            reserver = reserver[0]
        product.reserved_by = reserver
        has_reserved = False if (user is None or reserver is None) else user.user.user_id == reserver.user_id
    return templates.TemplateResponse(
        request=request, name="item.jinja", context={"item": None, "name": name, "is_admin": is_admin, "product": product, "product_images": product_images, "time": int(time.time()) if product.draft else 0, "has_reserved": has_reserved}
    )

@app.get("/item/{product_id}/edit")
async def product_edit(request: Request, product_id: str):
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    name = f"{user.user.first_name} {user.user.surname}" if user is not None else None
    async with connection.begin() as session:
        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if product is None:
            return RedirectResponse(app.url_path_for("home"))
        product = product[0]
        product_images = (await session.execute(select(ProductImage).filter_by(product_id=product_id).order_by(ProductImage.position))).all()
        product_images = [product_image[0] for product_image in product_images]
    return templates.TemplateResponse(
        request=request, name="product_edit.jinja", context={"name": name, "is_admin": True, "product": product, "images": product_images, "time": int(time.time())}
    )

@app.get("/admin/new_product")
async def new_product(request: Request):
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    name = f"{user.user.first_name} {user.user.surname}" if user is not None else None
    return templates.TemplateResponse(
        request=request, name="new_product.jinja", context={"name": name, "is_admin": True}
    )

@app.post("/admin/new_product")
async def new_product_post(request: Request, name: str = Form(""), brand: str = Form(""), description: str = Form(""), category: str = Form("")):
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    if len(name) < 3:
        return RedirectResponse(app.url_path_for("new_product"))
    if category not in CATEGORIES:
        return RedirectResponse(app.url_path_for("new_product"))
    uid = str(uuid.uuid4())
    t = int(time.time())
    async with connection.begin() as session:
        product = Product(
            product_id=uid,
            name=name,
            brand=brand,
            description=description,
            category=category,
            size="",
            default_image_id="",
            archived=False,
            draft=True,
            teacher=False,
            limit_to_teachers=False,
            state=-1,
            color="",
            material="",
            published_by=user.user.user_id,
            published_at=t,
            last_edited_by=user.user.user_id,
            last_edited_at=t,
        )
        session.add(product)
    return RedirectResponse(app.url_path_for("product_edit", product_id=uid), status_code=status.HTTP_303_SEE_OTHER)

@app.post("/item/{product_id}/edit")
async def product_edit_post(request: Request,
                            product_id: str,
                            name: str = Form(""),
                            brand: str = Form(""),
                            description: str = Form(""),
                            category: str = Form(""),
                            size: str = Form(""),
                            material: str = Form(""),
                            color: str = Form(""),
                            state: int = Form(-1),
                            archived: bool = Form(False),
                            teacher: bool = Form(False),
                            limit_to_teachers: bool = Form(False),
                            draft: bool = Form(False)):
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    if len(name) < 3:
        return RedirectResponse(app.url_path_for("new_product"))
    if category not in CATEGORIES:
        return RedirectResponse(app.url_path_for("new_product"))
    async with connection.begin() as session:
        pi = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if pi is None:
            # Taka slika ne obstaja v podatkovni bazi, preusmerimo uporabnika domov.
            return RedirectResponse(app.url_path_for("home"))
        pi = pi[0]
        pi.name = name
        pi.brand = brand
        pi.description = description
        pi.category = category
        pi.size = size
        pi.archived = archived
        pi.teacher = teacher
        if teacher:
            pi.limit_to_teachers = limit_to_teachers
        else:
            pi.limit_to_teachers = False
        if state in ALLOWED_PRODUCT_STATES:
            pi.state = state
        if material == "" or material in MATERIALS:
            pi.material = material
        if color == "" or color in COLORS:
            pi.color = color
        pi.draft = draft
        pi.last_edited_by = user.user.user_id
        pi.last_edited_at = int(time.time())
    return RedirectResponse(app.url_path_for("product_edit", product_id=product_id), status_code=status.HTTP_303_SEE_OTHER)

@app.get("/item/{product_id}/delete")
async def delete_product(request: Request, product_id: str):
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        product_images = (await session.execute(select(ProductImage).filter_by(product_id=product_id))).all()
        product_images = [product_image[0] for product_image in product_images]
        for image in product_images:
            try:
                os.remove(f"uploads/images/{image.image_id}.png")
            except:
                pass
        await session.execute(delete(ProductImage).filter_by(product_id=product_id))
        await session.execute(delete(Product).filter_by(product_id=product_id))
    return RedirectResponse(app.url_path_for("home"), status_code=status.HTTP_303_SEE_OTHER)

@app.get("/item/{product_id}/archive")
async def archive_product(request: Request, product_id: str, referer: typing.Annotated[str | None, Header()] = None):
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one()
        product = product[0]
        product.archived = not product.archived
        product.last_edited_by = user.user.user_id
        product.last_edited_at = int(time.time())
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)

@app.get("/item/{product_id}/reserve")
async def product_reserve(request: Request, product_id: str, referer: typing.Annotated[str | None, Header()] = None):
    user = get_session_user(request.cookies.get("session"))
    if user is None:
        return RedirectResponse(app.url_path_for("item_details", item_id=product_id),
                                status_code=status.HTTP_303_SEE_OTHER)
    async with connection.begin() as session:
        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if product is None:
            return RedirectResponse(app.url_path_for("home"))
        product = product[0]
        if product.archived:
            return RedirectResponse(app.url_path_for("item_details", item_id=product_id),
                                    status_code=status.HTTP_303_SEE_OTHER)
        if product.reserved_by_id == user.user.user_id:
            product.reserved_by_id = None
        elif not (product.reserved_by_id == "" or product.reserved_by_id is None):
            return RedirectResponse(app.url_path_for("item_details", item_id=product_id),
                                    status_code=status.HTTP_303_SEE_OTHER)
        else:
            product.reserved_by_id = user.user.user_id
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)

@app.get("/item/{product_id}/draft")
async def draft_undraft_product(request: Request, product_id: str, referer: typing.Annotated[str | None, Header()] = None):
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one()
        product = product[0]
        product.draft = not product.draft
        product.last_edited_by = user.user.user_id
        product.last_edited_at = int(time.time())
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)



@app.post("/item/{product_id}/upload_image")
async def upload_image(request: Request, product_id: str, file: UploadFile, description: str = Form("")):
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        uid = str(uuid.uuid4())
        contents = await file.read()
        img = Image.open(io.BytesIO(contents))
        img.save(f"uploads/images/{uid}-original.webp", optimize=True, quality=80)
        img.thumbnail((1100, 1100))
        img.save(f"uploads/images/{uid}.webp", optimize=True, quality=80)
        img.thumbnail((500, 500))
        img.save(f"uploads/images/{uid}-small.webp", optimize=True, quality=80)
        product_images = (await session.execute(select(ProductImage).filter_by(product_id=product_id))).all()
        order = len(product_images)
        product_image = ProductImage(
            image_id=uid,
            description=description,
            position=order,
            product_id=product_id,
        )
        session.add(product_image)
        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if product is None:
            return RedirectResponse(app.url_path_for("home"))
        product = product[0]
        if product.default_image_id is None or product.default_image_id == "":
            product.default_image_id = uid

    return RedirectResponse(app.url_path_for("product_edit", product_id=product_id), status_code=status.HTTP_303_SEE_OTHER)


def rotate_image(image_id: str, rotate: int):
    with Image.open(f"uploads/images/{image_id}.webp") as im:
        im_rotated = im.rotate(rotate, expand=1)
        im_rotated.save(f"uploads/images/{image_id}.webp")

@app.get("/image/{image_id}/rotate/right")
async def rotate_image_right(request: Request, image_id: str):
    # Prvo preverimo, da ima uporabnik veljaven session in je administrator
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))

    # Zaženemo povezavo s podatkovno bazo
    async with connection.begin() as session:
        # Preverimo, da taka slika sploh obstaja, saj se zanašamo na to, da pridobimo product_id
        pi = (await session.execute(select(ProductImage).filter_by(image_id=image_id))).one_or_none()
        if pi is None:
            # Taka slika ne obstaja v podatkovni bazi, preusmerimo uporabnika domov.
            return RedirectResponse(app.url_path_for("home"))
        pi = pi[0]

        rotate_image(f"{image_id}-original", -90)
        rotate_image(f"{image_id}", -90)
        rotate_image(f"{image_id}-small", -90)

    return RedirectResponse(app.url_path_for("product_edit", product_id=pi.product_id), status_code=status.HTTP_303_SEE_OTHER)


@app.get("/image/{image_id}/rotate/left")
async def rotate_image_left(request: Request, image_id: str):
    # Prvo preverimo, da ima uporabnik veljaven session in je administrator
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))

    # Zaženemo povezavo s podatkovno bazo
    async with connection.begin() as session:
        # Preverimo, da taka slika sploh obstaja, saj se zanašamo na to, da pridobimo product_id
        pi = (await session.execute(select(ProductImage).filter_by(image_id=image_id))).one_or_none()
        if pi is None:
            # Taka slika ne obstaja v podatkovni bazi, preusmerimo uporabnika domov.
            return RedirectResponse(app.url_path_for("home"))
        pi = pi[0]

        rotate_image(f"{image_id}-original", 90)
        rotate_image(f"{image_id}", 90)
        rotate_image(f"{image_id}-small", 90)

    return RedirectResponse(app.url_path_for("product_edit", product_id=pi.product_id), status_code=status.HTTP_303_SEE_OTHER)



@app.get("/image/{image_id}/delete")
async def delete_image(request: Request, image_id: str, referer: typing.Annotated[str | None, Header()] = None):
    # Prvo preverimo, da ima uporabnik veljaven session in je administrator
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))

    # Zaženemo povezavo s podatkovno bazo
    async with connection.begin() as session:
        # Preverimo, da taka slika sploh obstaja, saj se zanašamo na to, da pridobimo product_id
        pi = (await session.execute(select(ProductImage).filter_by(image_id=image_id))).one_or_none()
        if pi is None:
            # Taka slika ne obstaja v podatkovni bazi, preusmerimo uporabnika domov.
            return RedirectResponse(app.url_path_for("home"))
        pi = pi[0]
        product_id = pi.product_id

        # Pridobimo produkt, saj moramo preveriti, da default_image_id ni enak enoličnemu identifikatorju slike, ki
        # jo brišemo.
        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if product is None:
            # Takega produkta nekako ni, preusmerimo uporabnika domov.
            return RedirectResponse(app.url_path_for("home"))
        product = product[0]

        # Iz podatkovne baze izbrišemo sliko, efektivno jo odstranimo iz sistema
        await session.delete(pi)

        # Pridobimo vse slike izdelka, ki imajo position večji od positiona izbrisane slike.
        # Tem slikam moramo zmanjšati position, da zagotovimo ustrezno zaporedje.
        product_images = (await session.execute(select(ProductImage).filter(ProductImage.product_id == product_id, ProductImage.position >= pi.position).order_by(ProductImage.position))).all()
        product_images = [product_image[0] for product_image in product_images]
        for product_image in product_images:
            product_image.position -= 1

        # Nastavimo nov product image, če je bila izbrisana slika product image
        # Nastavimo na po poziciji prvo sliko izdelka, če taka obstaja, saj je zagotovljeno, da ima default image
        # najmanjši position.
        if product.default_image_id == image_id:
            if len(product_images) == 0:
                product.default_image_id = ""
            else:
                product.default_image_id = product_images[0].image_id

        try:
            # Poskusimo izbrisati sliko iz strežnika. Če nam ne uspe, ni problema, lahko nadaljujemo.
            os.remove(f"uploads/images/{image_id}.webp")
            os.remove(f"uploads/images/{image_id}-small.webp")
            os.remove(f"uploads/images/{image_id}-original.webp")
            os.remove(f"uploads/images/{image_id}.png")
        except:
            pass

    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin/panel")
@app.post("/admin/panel")
async def admin(request: Request, user_name: str = Form("")):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))

    search_results = None
    if request.method.lower() == "post":
        user_name = urllib.parse.quote_plus(user_name)
        async with httpx.AsyncClient() as client:
            client.headers = {"Authorization": f"Bearer {user.microsoft_token}", "ConsistencyLevel": "eventual"}
            url = f"https://graph.microsoft.com/v1.0/users?$count=true&$search=\"displayName:{user_name}\"&$orderBy=displayName&$select=id,displayName,mail,userPrincipalName,department"
            user_response = await client.get(url)
            #print(client.headers["Authorization"], user_response.status_code, url, user_response.json())
            if user_response.status_code == 200:
                search_results = user_response.json()["value"]
                #print(search_results)
    async with connection.begin() as session:
        users = (await session.execute(select(User).order_by(User.surname))).all()
        users: List[User] = [user[0] for user in users]

        reservations = (await session.execute(select(Product).filter(Product.reserved_by_id is not None and Product.reserved_by_id != "").filter_by(archived=False))).all()
        reservations: List[Product] = [product[0] for product in reservations]
        for user in users:
            for i, v in enumerate(reservations):
                if user.user_id != v.reserved_by_id:
                    continue
                reservations[i].reserved_by = user
        reservations.sort(key=lambda e: e.reserved_by.surname)
    return templates.TemplateResponse(
        request=request, name="admin.jinja", context={
            "users": users,
            "reservations": reservations,
            "search_results": search_results,
        }
    )


@app.post("/admin/user/{user_id}/manage")
async def admin_user_manage_post(request: Request, user_id: str, credits: int = Form(0), admin: bool = Form(False), teacher: bool = Form(False)):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))

    async with connection.begin() as session:
        user = (await session.execute(select(User).filter_by(user_id=user_id))).one_or_none()
        if user is None:
            return RedirectResponse(app.url_path_for("admin"), status_code=status.HTTP_303_SEE_OTHER)
        user = user[0]
        user.credits = credits
        user.is_admin = admin
        user.is_teacher = teacher
    return RedirectResponse(app.url_path_for("admin"), status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/user/{user_id}/delete")
async def admin_user_delete_post(request: Request, user_id: str):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        await session.execute(delete(User).filter_by(user_id=user_id))
    return RedirectResponse(app.url_path_for("admin"), status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/reservation/{product_id}/delete")
async def admin_reservation_delete_post(request: Request, product_id: str):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        reservation = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if reservation is None or reservation[0] is None:
            return RedirectResponse(app.url_path_for("admin"), status_code=status.HTTP_303_SEE_OTHER)
        reservation = reservation[0]
        reservation.reserved_by_id = None
    return RedirectResponse(app.url_path_for("admin"), status_code=status.HTTP_303_SEE_OTHER)



@app.get("/admin/user/{user_id}/create")
async def admin_user_account_create(request: Request, user_id: str):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))
    user_id = urllib.parse.quote_plus(user_id)
    async with httpx.AsyncClient() as client:
        client.headers = {"Authorization": f"Bearer {user.microsoft_token}"}
        user_response = await client.get(f"https://graph.microsoft.com/v1.0/users/{user_id}")
        if user_response.status_code != 200:
            return RedirectResponse(app.url_path_for("admin"), status_code=status.HTTP_303_SEE_OTHER)
        response = user_response.json()
        is_teacher = "@gimb.org" in response["mail"]  # dijaki imajo @dijaki.gimb.org mejl. Torej lahko zdeduciramo, da so @gimb.org naslovi rezervirani za učitelje
        first_name: str = response["givenName"]  # Ime
        surname: str = response["surname"]  # Priimek
        user_principal_name: str = response["userPrincipalName"]  # @gimb.org elektronski naslov
        user_id: str = response["id"]  # Uporabniški ID, kakršen je določen za uporabnika v Azure Active Direktoriju (oz. zdaj Microsoft Entra ID)
    async with connection.begin() as session:
        u = (await session.execute(select(User).filter_by(user_id=user_id))).one_or_none()
        if u is not None:
            return RedirectResponse(app.url_path_for("admin"))
        u = User(
            user_id=user_id,
            email=user_principal_name,
            first_name=first_name,
            surname=surname,
            credits=0,
            session_token=None,
            is_admin=False,
            is_teacher=is_teacher,
        )
        session.add(u)
    return RedirectResponse(app.url_path_for("admin"), status_code=status.HTTP_303_SEE_OTHER)


@app.get("/image/{image_id}/move/{up_down}")
async def move_image_up_down(request: Request, image_id: str, up_down: str):
    # Prvo preverimo, da ima uporabnik veljaven session in je administrator
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))

    if up_down != "up" and up_down != "down":
        # Če up_down ne ustreza nobeni izmed teh dveh možnosti, ne vemo, kaj narediti
        return RedirectResponse(app.url_path_for("home"))

    # Zaženemo povezavo s podatkovno bazo
    async with connection.begin() as session:
        # Preverimo, da taka slika sploh obstaja, saj se zanašamo na to, da pridobimo product_id
        pi = (await session.execute(select(ProductImage).filter_by(image_id=image_id))).one_or_none()
        if pi is None:
            # Taka slika ne obstaja v podatkovni bazi, preusmerimo uporabnika domov.
            return RedirectResponse(app.url_path_for("home"))
        pi = pi[0]
        product_id = pi.product_id

        # Pridobimo produkt, saj moramo preveriti, da default_image_id ni enak enoličnemu identifikatorju slike, ki
        # jo premikamo.
        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if product is None:
            # Takega produkta nekako ni, preusmerimo uporabnika domov.
            return RedirectResponse(app.url_path_for("home"))
        product = product[0]

        product_images = (await session.execute(select(ProductImage).filter(ProductImage.product_id == product_id).order_by(ProductImage.position))).all()
        product_images = [product_image[0] for product_image in product_images]

        if product_images[0].image_id == image_id and up_down == "up":
            # Slike ne moremo prestaviti še bolj gor, če je že tako ali tako prva
            return RedirectResponse(app.url_path_for("product_edit", product_id=product_id),
                                    status_code=status.HTTP_303_SEE_OTHER)
        if product_images[-1].image_id == image_id and up_down == "down":
            # Slike ne moremo prestaviti še bolj dol, če je že tako ali tako zadnja
            return RedirectResponse(app.url_path_for("product_edit", product_id=product_id),
                                    status_code=status.HTTP_303_SEE_OTHER)

        prev_position = pi.position
        new_position = pi.position + 1 if up_down == "down" else pi.position - 1
        pi.position = new_position

        # Če gremo v katerokoli smer, samo zamenjamo obe sliki
        # Pri tem poskrbimo, da nobena izmed slik ni bila default_image_id na productu
        product_images = (await session.execute(select(ProductImage).filter_by(product_id=product_id, position=new_position))).all()
        product_images = [product_image[0] for product_image in product_images]
        #[print(product_image.image_id, product_image.position) for product_image in product_images]
        for image in product_images:
            # Če je to slika, ki jo zamenjujemo, jo preskočimo, ker smo že prej nastavili nov position
            if image.image_id == image_id:
                continue
            #print(image.image_id)
            image.position = prev_position
            break

        # Na novo nastavimo default_image_id
        product_image = (await session.execute(select(ProductImage).filter(ProductImage.product_id == product_id).order_by(ProductImage.position))).first()
        product_image = product_image[0]
        product.default_image_id = product_image.image_id

    return RedirectResponse(app.url_path_for("product_edit", product_id=product_id), status_code=status.HTTP_303_SEE_OTHER)


@app.get("/image/{image_id}/default")
async def set_image_default(request: Request, image_id: str):
    # Prvo preverimo, da ima uporabnik veljaven session in je administrator
    user = get_session_user(request.cookies.get("session"))
    if user is None or not user.user.is_admin:
        return RedirectResponse(app.url_path_for("home"))

    # Zaženemo povezavo s podatkovno bazo
    async with connection.begin() as session:
        # Preverimo, da taka slika sploh obstaja, saj se zanašamo na to, da pridobimo product_id
        pi = (await session.execute(select(ProductImage).filter_by(image_id=image_id))).one_or_none()
        if pi is None:
            # Taka slika ne obstaja v podatkovni bazi, preusmerimo uporabnika domov.
            return RedirectResponse(app.url_path_for("home"))
        pi = pi[0]
        product_id = pi.product_id

        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if product is None:
            # Takega produkta nekako ni, preusmerimo uporabnika domov.
            return RedirectResponse(app.url_path_for("home"))
        product = product[0]

        product_image = (await session.execute(select(ProductImage).filter_by(image_id=product.default_image_id))).one()
        product_image = product_image[0]

        prev_position = pi.position
        new_position = product_image.position
        pi.position = new_position

        product_image.position = prev_position
        pi.position = new_position
        product.default_image_id = image_id

    return RedirectResponse(app.url_path_for("product_edit", product_id=product_id), status_code=status.HTTP_303_SEE_OTHER)


@app.get("/language")
async def set_language(lang: str = "sl", referer: typing.Annotated[str | None, Header()] = None):
    redirect_response = RedirectResponse(referer)
    if lang not in SUPPORTED_LANGUAGES:
        lang = "sl"
    redirect_response.set_cookie(key="lang", value=lang, httponly=True, secure=True)
    return redirect_response


@app.get("/logout")
async def logout(request: Request):
    redirect_response = RedirectResponse(app.url_path_for("home"))
    redirect_response.set_cookie(key="session", value="", httponly=True, secure=True)

    user = get_session_user(request.cookies.get("session"))
    if user is None:
        return redirect_response
    async with connection.begin() as session:
        result = (await session.execute(select(User).filter_by(user_id=user.user.user_id))).one_or_none()
        if result is None:
            # Takega uporabnika ni v podatkovni bazi
            return redirect_response

        result = result[0]

        # Izbrišemo session v cachu
        session_token = result.session_token
        del sessions[session_token]

        # Ponastavimo session token
        result.session_token = None
    return redirect_response


@app.get("/microsoft/login/url")
async def microsoft_login_redirect(request: Request):
    return RedirectResponse(
        f"https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?client_id={MICROSOFT_CLIENT_ID}&response_type=code&response_mode=query&scope={SCOPE}")


@app.get("/microsoft/login/auth")
async def microsoft_login_callback(request: Request, code: str):
    async with httpx.AsyncClient() as client:
        body = {
            "client_id": MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "code": code,
            "scope": SCOPE,
            "grant_type": "authorization_code",
        }

        # Zahtevamo avtorizacijski token za prijavljenega uporabnika od Microsofta
        login_response = await client.post("https://login.microsoftonline.com/organizations/oauth2/v2.0/token",
                                           data=body)
        if login_response.status_code != 200:
            # Statusna koda, ki nam jo je vrnil Microsoft ob zahtevku ni bila 200 (OK). To pomeni, da je nekaj nekje šlo narobe.
            return RedirectResponse(app.url_path_for("home") + "?login_success=False")

        # Uspešno smo pridobili avtorizacijski token, zdaj lahko v imenu uporabnika izvajamo zahtevke na Microsoftovem API-ju.
        expires_on = int(time.time()) + int(login_response.json()["expires_in"]) # Čas, ki nam ga posreduje Microsoft, je v sekundah.
        access_token = login_response.json()["access_token"]
        client.headers = {"Authorization": f"Bearer {access_token}"}

        # Zahtevamo uporabnike podatke preko Microsoft Graph API-ja
        # https://developer.microsoft.com/en-us/graph/graph-explorer
        user_response = await client.get("https://graph.microsoft.com/v1.0/me")
        if user_response.status_code != 200:
            # Statusna koda, ki nam jo je vrnil Microsoft ob zahtevku ni bila 200 (OK). To pomeni, da je nekaj nekje šlo narobe.
            return RedirectResponse(app.url_path_for("home") + "?login_success=False")

        # Uspešno smo pridobili uporabniške podatke. S tem smo hkrati preverili veljavnost avtorizacijskega tokena,
        # ki nam ga je poslal Microsoft. V nadaljnje ne bomo več potrebovali tega avtorizacijskega tokena, razen
        # ob nadaljnjih prijavah.
        response = user_response.json()
        is_teacher = "@gimb.org" in response["mail"] # dijaki imajo @dijaki.gimb.org mejl. Torej lahko zdeduciramo, da so @gimb.org naslovi rezervirani za učitelje
        first_name: str = response["givenName"]  # Ime
        surname: str = response["surname"]  # Priimek
        user_principal_name: str = response["userPrincipalName"]  # @gimb.org elektronski naslov
        user_id: str = response["id"]  # Uporabniški ID, kakršen je določen za uporabnika v Azure Active Direktoriju (oz. zdaj Microsoft Entra ID)

    # Pogledamo v podatkovno bazo, ali tak uporabnik že obstaja
    async with connection.begin() as session:
        user = (await session.execute(select(User).filter_by(user_id=user_id))).one_or_none()
        if user is None:
            # Takega uporabnika ni v podatkovni bazi
            # V takem primeru ustvarimo uporabniški profil
            # Aplikacija je tako ali tako preko Graph API-ja omejena zgolj na tenant "Gimnazija Bežigrad"
            # Tako da so z gotovostjo vsi, ki se prijavljajo, nekako povezani z GIMB
            user = User(
                user_id=user_id,
                email=user_principal_name,
                first_name=first_name,
                surname=surname,
                credits=0,
                session_token=None,
                is_admin=False,
                is_teacher=is_teacher,
            )
        else:
            user = user[0]

        # Zgeneriramo nov session token za uporabnika, če ga še nima
        if user.session_token is None:
            user.session_token = random_session_token()

        user.is_teacher = is_teacher

        session.add(user)

        # Pošljemo session token kot piškotek (cookie) nazaj
        redirect_response = RedirectResponse(app.url_path_for("home") + "?login_success=True")
        redirect_response.set_cookie(key="session", value=user.session_token, httponly=True, secure=True)

        # Ta session token shranimo v cache
        sessions[user.session_token] = UserSession(user, access_token, expires_on)

        # Na koncu se vse avtomatično comitta v podatkovno bazo

    return redirect_response
