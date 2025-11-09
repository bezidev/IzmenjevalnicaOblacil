import asyncio
import datetime
import html
import io
import smtplib
import ssl
import time
import typing
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
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

SEND_MAILS_PEOPLE = os.environ["SEND_MAILS_PEOPLE"].split(",")

EMAIL_SERVER = os.environ["EMAIL_SERVER"]
EMAIL_USERNAME = os.environ["EMAIL_USERNAME"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]

# Create a secure SSL context
context = ssl.create_default_context()

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

def timectime(s):
    return time.ctime(s) # datetime.datetime.fromtimestamp(s)

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

async def send_mail():
    async with connection.begin() as session:
        products = (await session.execute(select(Product).filter(Product.reserved_by_id != None, Product.reserved_by_id != "", Product.reservation_mail_sent == False))).all()
        if len(products) == 0:
            return
        reservation = "Pozdravljeni!<p></p>Na izmenjevalnici oblačil so se pojavile naslednje nove rezervacije:<br>"
        for product in products:
            product = product[0]
            reserver = (await session.execute(select(User).filter_by(user_id=product.reserved_by_id))).one_or_none()
            reserver: User = reserver[0]
            reservation += f'<b>{html.escape(reserver.first_name)} {html.escape(reserver.surname)}</b>: <a href="https://izmenjevalnica.gimb.org/item/{product.product_id}">{html.escape(product.name)}</a><br>'
        reservation += '<p></p>Da pogledate vse rezervacije, se prijavite v portal in dostopajte do <a href="https://izmenjevalnica.gimb.org/admin/panel">administratorske plošče</a>.<br>'
        reservation += '<p></p>Lep pozdrav<br>Sistem izmenjevalnice oblačil<p></p><hr>To sporočilo je avtomatizirano. Prejemate ga, ker ste označeni za pomembno osebo v sistemu. Če mislite, da je to napaka, sporočite razvijalcu.<p></p>Uradna sporočila iz izmenjevalnice bodo vedno prihajala iz elektronskega naslova izmenjevalnica@beziapp.si. Če opazite drugačen naslov, prijavite incident razvijalcu na <a href="mailto:mitja.severkar@gimb.org">mitja.severkar@gimb.org</a>.<br>RAZVIJALEC VAS NIKOLI NE BO VPRAŠAL PO VAŠEM GESLU, NITI PO ELEKTRONSKI POŠTI NITI V ŽIVO.'
        message = MIMEMultipart("alternative")
        message["Subject"] = "Nove rezervacije na šolski izmenjevalnici oblačil"
        message["From"] = EMAIL_USERNAME
        message["To"] = ", ".join(SEND_MAILS_PEOPLE)
        message["Date"] = formatdate(localtime=True)
        message.attach(MIMEText(reservation, "html"))
        with smtplib.SMTP_SSL(EMAIL_SERVER, 465, context=context) as server:
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.sendmail(EMAIL_USERNAME, SEND_MAILS_PEOPLE, message.as_string())
        for product in products:
            product = product[0]
            product.reservation_mail_sent = True


MAIL_SEND_DELAY = 60 * 60 * 24
async def send_mails_coroutine():
    t = datetime.datetime.now().replace(hour=14, minute=0, second=0)
    if datetime.datetime.now() > t:
        t += timedelta(days=1)
    delta = int(t.timestamp()) - int(time.time())
    print(f"Sleeping for {delta} seconds before sending")
    await asyncio.sleep(delta)
    while True:
        print(f"Sending mail")
        try:
            await send_mail()
            print(f"Sending done")
        except Exception as e:
            print(f"Failure sending e-mails: {e}")
        await asyncio.sleep(MAIL_SEND_DELAY)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Executed on startup
    async with engine.begin() as conn:
        print("Creating database!")
        await conn.run_sync(Base.metadata.create_all)
    asyncio.create_task(send_mails_coroutine())

    # One-time migrations
    """
    async with connection.begin() as session:
        products = (await session.execute(select(Product))).all()
        for product in products:
            product = product[0]
            product.gender = "unisex"
            if "women" in product.category:
                product.gender = "women"
            elif "men" in product.category:
                product.gender = "men"

            if "sweater" in product.category:
                product.category = "sweater"
            if "shirts" in product.category:
                product.category = "shirts"
            if "jacket" in product.category:
                product.category = "jacket"
            if "pants" in product.category:
                product.category = "pants"
            if "skirts" in product.category:
                product.category = "skirts"
            if "dress" in product.category:
                product.category = "dresses"
            if "shoes" in product.category:
                product.category = "shoes"
    """
    yield
    # Executed after end

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="static")
templates = Jinja2Templates(directory="templates", context_processors=[app_context])
templates.env.filters["translate"] = translate
templates.env.filters["translate_number"] = translate_number
templates.env.filters["ctime"] = timectime

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

        categories: str = "",
        colors: str = "",
        genders: str = "",
        materials: str = "",
        sizes: str = "",
        states: str = "",

        size_from: int = -1,
        size_to: int = -1,

        teacher: bool = False,
        my_reservations: bool = False,
):
    user = get_session_user(request.cookies.get("session"))
    credits = user.user.credits if user is not None else 0
    name = f"{user.user.first_name} {user.user.surname}" if user is not None else None
    is_admin = False if user is None else user.user.is_admin
    is_teacher = False if user is None else user.user.is_teacher

    # Če je vse uncheckano, checkamo zadeve
    if not active and not archived and not draft:
        active = True
        archived = False
        draft = True

    if not (size_from < 0 or size_to < 0) and size_to < size_from:
        size_from, size_to = size_to, size_from

    select_all_categories = True
    select_all_genders = True
    select_all_materials = True
    select_all_colors = True
    select_all_sizes = True
    select_all_shoe_sizes = True
    select_all_states = True

    if categories != "":
        categories = categories.split(",")
        select_all_categories = False
        for i in categories:
            if i not in CATEGORIES:
                select_all_categories = True
                break
    else:
        categories = []

    if genders != "":
        genders = genders.split(",")
        select_all_genders = False
        for i in genders:
            if i not in ["male", "female", "unisex"]:
                select_all_genders = True
                break
    else:
        genders = []

    if materials != "":
        materials = materials.split(",")
        select_all_materials = False
        for i in materials:
            if i not in MATERIALS:
                select_all_materials = True
                break
    else:
        materials = []

    if colors != "":
        colors = colors.split(",")
        select_all_colors = False
        for i in colors:
            if i not in COLORS:
                select_all_colors = True
                break
    else:
        colors = []

    if sizes != "":
        sizes = sizes.split(",")
        select_all_sizes = False
        for i in sizes:
            if i not in ["XXS", "XS", "S", "M", "L", "XL", "XXL"]:
                select_all_sizes = True
                break
    else:
        sizes = []
    if size_from >= 0 or size_to >= 0:
        select_all_shoe_sizes = False

    if states != "":
        states = states.split(",")
        select_all_states = False
        for i in states:
            if int(i) not in ALLOWED_PRODUCT_STATES:
                select_all_states = True
                break
    else:
        states = []

    reserved_products = 0
    async with (connection.begin() as session):
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
        products_filtered3 = []
        products_filtered4 = []
        products_filtered5 = []
        products_filtered6 = []
        products_filtered7 = []
        for product in products:
            if product.reserved_by_id == (user.user.user_id if user is not None else ""):
                reserved_products += 1
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

        if not select_all_categories:
            for product in products_filtered:
                if product.category in categories:
                    products_filtered2.append(product)
        else:
            products_filtered2 = products_filtered

        if not select_all_genders:
            for product in products_filtered2:
                if product.gender in genders:
                    products_filtered3.append(product)
        else:
            products_filtered3 = products_filtered2

        if not select_all_colors:
            for product in products_filtered3:
                if product.color in colors:
                    products_filtered4.append(product)
        else:
            products_filtered4 = products_filtered3

        if not select_all_materials:
            for product in products_filtered4:
                if product.material in materials:
                    products_filtered5.append(product)
        else:
            products_filtered5 = products_filtered4

        for product in products_filtered5:
            if not PRODUCT_CATEGORIES[product.category]["has_size"]:
                products_filtered6.append(product)
                continue

            if product.category == "shoes":
                if select_all_shoe_sizes:
                    products_filtered6.append(product)
                    continue

                try:
                    sz = int(product.size)
                except:
                    print(f"[ERROR] Parsing shoe size: {product.size}")
                    continue
                if (size_from < 0 or sz >= size_from) and (size_to < 0 or sz <= size_to):
                    products_filtered6.append(product)
            else:
                if select_all_sizes:
                    products_filtered6.append(product)
                    continue

                if product.size in sizes:
                    products_filtered6.append(product)

        if not select_all_states:
            for product in products_filtered6:
                if str(product.state) in states:
                    products_filtered7.append(product)
        else:
            products_filtered7 = products_filtered6

        products_final = products_filtered7

        if sort == "":
            products_final.sort(key=sort_by_modified_date, reverse=True)
        elif sort == "last-changed-asc":
            products_final.sort(key=sort_by_modified_date)
        elif sort == "created-desc":
            products_final.sort(key=sort_by_creation_date, reverse=True)
        elif sort == "created-asc":
            products_final.sort(key=sort_by_creation_date)
        elif sort == "alphabet-asc":
            products_final.sort(key=sort_by_name)
        elif sort == "alphabet-desc":
            products_final.sort(key=sort_by_name, reverse=True)
        elif sort == "size-asc":
            products_final.sort(key=sort_by_size)
        elif sort == "size-desc":
            products_final.sort(key=sort_by_size, reverse=True)

    if size_to < 0:
        size_to = None
    if size_from < 0:
        size_from = None

    return templates.TemplateResponse(
        request=request, name="home.jinja", context={
            "login_success": login_success,
            "name": name,
            "is_admin": is_admin,
            "is_teacher": is_teacher,
            "products": products_final,
            "sorting_method": sort,
            "credits": credits,
            "reserved_products": reserved_products,
            "filter_categories": categories,
            "filter_sizes": sizes,
            "filter_colors": colors,
            "filter_materials": materials,
            "filter_genders": genders,
            "filter_size_from": size_from,
            "filter_size_to": size_to,
            "filter_states": states,
            "filters": {
                "filter_active": active,
                "filter_archived": archived,
                "filter_draft": draft,
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
        sweater: bool = Form(False),
        cardigans: bool = Form(False),
        shirts: bool = Form(False),
        dress_shirts: bool = Form(False),
        blouses: bool = Form(False),
        jacket: bool = Form(False),
        pants: bool = Form(False),
        skirts: bool = Form(False),
        dresses: bool = Form(False),
        shoes: bool = Form(False),
        accessories: bool = Form(False),

        gender_male: bool = Form(False),
        gender_female: bool = Form(False),
        gender_unisex: bool = Form(False),

        cotton: bool = Form(False),
        kapok: bool = Form(False),
        hemp: bool = Form(False),
        flax: bool = Form(False),
        wool: bool = Form(False),
        mohair: bool = Form(False),
        silk: bool = Form(False),
        feathers: bool = Form(False),
        polyester: bool = Form(False),
        spandex: bool = Form(False),
        nylon: bool = Form(False),
        leather: bool = Form(False),
        artificial_leather: bool = Form(False),
        viscose: bool = Form(False),
        mixed_materials: bool = Form(False),
        artificial_materials: bool = Form(False),

        red: bool = Form(False),
        orange: bool = Form(False),
        yellow: bool = Form(False),
        green: bool = Form(False),
        cyan: bool = Form(False),
        blue: bool = Form(False),
        pink: bool = Form(False),
        purple: bool = Form(False),
        beige: bool = Form(False),
        white: bool = Form(False),
        brown: bool = Form(False),
        grey: bool = Form(False),
        black: bool = Form(False),
        colorful: bool = Form(False),

        size_xxs: bool = Form(False),
        size_xs: bool = Form(False),
        size_s: bool = Form(False),
        size_m: bool = Form(False),
        size_l: bool = Form(False),
        size_xl: bool = Form(False),
        size_xxl: bool = Form(False),

        size_from: int = Form(-1),
        size_to: int = Form(-1),

        state_unknown: bool = Form(False),
        state_poor: bool = Form(False),
        state_medium: bool = Form(False),
        state_good: bool = Form(False),
        state_great: bool = Form(False),
        state_excellent: bool = Form(False),

        teacher: bool = Form(False),
        my_reservations: bool = Form(False),
):
    encode: dict[str, str | bool] = {
        "sort": sorting_method,
        "size_from": size_from,
        "size_to": size_to,
    }

    categories = []
    genders = []
    materials = []
    colors = []
    sizes = []
    states = []

    if active:
        encode["active"] = True
    if archived:
        encode["archived"] = True
    if draft:
        encode["draft"] = True

    if accessories:
        categories.append("accessories")
    if hat:
        categories.append("hat")
    if sunglasses:
        categories.append("sunglasses")
    if sweater:
        categories.append("sweater")
    if cardigans:
        categories.append("cardigans")
    if shirts:
        categories.append("shirts")
    if dress_shirts:
        categories.append("dress_shirts")
    if blouses:
        categories.append("blouses")
    if jacket:
        categories.append("jacket")
    if pants:
        categories.append("pants")
    if skirts:
        categories.append("skirts")
    if dresses:
        categories.append("dresses")
    if shoes:
        categories.append("shoes")
    encode["categories"] = ",".join(categories)

    if gender_male:
        genders.append("male")
    if gender_female:
        genders.append("female")
    if gender_unisex:
        genders.append("unisex")
    encode["genders"] = ",".join(genders)

    if cotton:
        materials.append("cotton")
    if kapok:
        materials.append("kapok")
    if hemp:
        materials.append("hemp")
    if flax:
        materials.append("flax")
    if wool:
        materials.append("wool")
    if mohair:
        materials.append("mohair")
    if silk:
        materials.append("silk")
    if feathers:
        materials.append("feathers")
    if polyester:
        materials.append("polyester")
    if spandex:
        materials.append("spandex")
    if nylon:
        materials.append("nylon")
    if leather:
        materials.append("leather")
    if artificial_leather:
        materials.append("artificial_leather")
    if viscose:
        materials.append("viscose")
    if mixed_materials:
        materials.append("mixed_materials")
    if artificial_materials:
        materials.append("artificial_materials")
    encode["materials"] = ",".join(materials)

    if red:
        colors.append("red")
    if orange:
        colors.append("orange")
    if yellow:
        colors.append("yellow")
    if green:
        colors.append("green")
    if cyan:
        colors.append("cyan")
    if blue:
        colors.append("blue")
    if pink:
        colors.append("pink")
    if purple:
        colors.append("purple")
    if beige:
        colors.append("beige")
    if white:
        colors.append("white")
    if brown:
        colors.append("brown")
    if grey:
        colors.append("grey")
    if black:
        colors.append("black")
    if colorful:
        colors.append("colorful")
    encode["colors"] = ",".join(colors)

    if size_xxs:
        sizes.append("XXS")
    if size_xs:
        sizes.append("XS")
    if size_s:
        sizes.append("S")
    if size_m:
        sizes.append("M")
    if size_l:
        sizes.append("L")
    if size_xl:
        sizes.append("XL")
    if size_xxl:
        sizes.append("XXL")
    encode["sizes"] = ",".join(sizes)

    if state_unknown:
        states.append("-1")
    if state_poor:
        states.append("50")
    if state_medium:
        states.append("75")
    if state_good:
        states.append("100")
    if state_great:
        states.append("200")
    if state_excellent:
        states.append("300")
    encode["states"] = ",".join(states)

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
            draft=False,
            teacher=False,
            limit_to_teachers=False,
            state=-1,
            color="",
            material="",
            gender="unisex",
            reserved_by_id="",
            reserved_date=0,
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
                            gender: str = Form(""),
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
        if gender in ["male", "female", "unisex"]:
            pi.gender = gender
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
            product.reservation_mail_sent = False
            product.reserved_date = time.time()
        elif not (product.reserved_by_id == "" or product.reserved_by_id is None):
            return RedirectResponse(app.url_path_for("item_details", item_id=product_id),
                                    status_code=status.HTTP_303_SEE_OTHER)
        else:
            product.reserved_by_id = user.user.user_id
            product.reservation_mail_sent = False
            product.reserved_date = time.time()
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

@app.get("/admin")
async def admin(request: Request):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))
    return templates.TemplateResponse(request=request, name="admin.jinja")

@app.get("/admin/reservations")
async def admin_reservations(request: Request):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))

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
        request=request, name="admin_reservations.jinja", context={
            "reservations": reservations,
        }
    )

@app.get("/admin/users")
@app.post("/admin/users")
async def admin_users(request: Request, user_name: str = Form("")):
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
    return templates.TemplateResponse(
        request=request, name="admin_users.jinja", context={
            "users": users,
            "search_results": search_results,
        }
    )

@app.post("/admin/user/{user_id}/manage")
async def admin_user_manage_post(request: Request, user_id: str, credits: int = Form(0), admin: bool = Form(False), teacher: bool = Form(False), referer: typing.Annotated[str | None, Header()] = None):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))

    async with connection.begin() as session:
        user = (await session.execute(select(User).filter_by(user_id=user_id))).one_or_none()
        if user is None:
            return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)
        user = user[0]
        user.credits = credits
        user.is_admin = admin
        user.is_teacher = teacher
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/admin/user/{user_id}/delete")
async def admin_user_delete_post(request: Request, user_id: str, referer: typing.Annotated[str | None, Header()] = None):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        await session.execute(delete(User).filter_by(user_id=user_id))
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/reservation/{product_id}/delete")
async def admin_reservation_delete_post(request: Request, product_id: str, referer: typing.Annotated[str | None, Header()] = None):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        reservation = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if reservation is None or reservation[0] is None:
            return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)
        reservation = reservation[0]
        reservation.reserved_by_id = None
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)



@app.get("/admin/user/{user_id}/create")
async def admin_user_account_create(request: Request, user_id: str, referer: typing.Annotated[str | None, Header()] = None):
    user = get_session_user(request.cookies.get("session"))
    is_admin = False if user is None else user.user.is_admin
    if not is_admin:
        return RedirectResponse(app.url_path_for("home"))
    user_id = urllib.parse.quote_plus(user_id)
    async with httpx.AsyncClient() as client:
        client.headers = {"Authorization": f"Bearer {user.microsoft_token}"}
        user_response = await client.get(f"https://graph.microsoft.com/v1.0/users/{user_id}")
        if user_response.status_code != 200:
            return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)
        response = user_response.json()
        is_teacher = "@gimb.org" in response["mail"]  # dijaki imajo @dijaki.gimb.org mejl. Torej lahko zdeduciramo, da so @gimb.org naslovi rezervirani za učitelje
        first_name: str = response["givenName"]  # Ime
        surname: str = response["surname"]  # Priimek
        user_principal_name: str = response["userPrincipalName"]  # @gimb.org elektronski naslov
        user_id: str = response["id"]  # Uporabniški ID, kakršen je določen za uporabnika v Azure Active Direktoriju (oz. zdaj Microsoft Entra ID)
    async with connection.begin() as session:
        u = (await session.execute(select(User).filter_by(user_id=user_id))).one_or_none()
        if u is not None:
            return RedirectResponse(referer)
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
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)


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
