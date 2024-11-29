import io
import time
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from typing import List

import aiofiles
import httpx
import os

from PIL import Image
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, delete
from starlette import status

from database import get_session_user, User, connection, random_session_token, sessions, Base, engine, Product, \
    ProductImage

load_dotenv()

# Poberemo skrivne vrednosti iz okoljskih spremenljivk
MICROSOFT_CLIENT_ID = os.environ["MICROSOFT_CLIENT_ID"]
MICROSOFT_CLIENT_SECRET = os.environ["MICROSOFT_CLIENT_SECRET"]
SCOPE = "https://graph.microsoft.com/User.Read"

CATEGORIES = [
    "hat",
    "sunglasses",
    "men-shirts",
    "women-shirts",
    "men-pants",
    "women-pants",
    "men-shoes",
    "women-shoes",
]

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
templates = Jinja2Templates(directory="templates")

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

@app.get("/", response_class=HTMLResponse)
async def home(
        request: Request,
        login_success: bool | None = None,
        sort: str = "",
        active: bool = False,
        archived: bool = False,
        draft: bool = False,
        hat: bool = False,
        sunglasses: bool = False,
        men_shirts: bool = False,
        women_shirts: bool = False,
        men_pants: bool = False,
        women_pants: bool = False,
        men_shoes: bool = False,
        women_shoes: bool = False,
):
    user = await get_session_user(request.cookies.get("session"))
    name = f"{user.first_name} {user.surname}" if user is not None else None
    is_admin = False if user is None else user.is_admin

    # Če je vse uncheckano, checkamo zadeve
    if not active and not archived and not draft:
        active = True
        archived = True
        draft = True
    if not hat and not sunglasses and not men_shirts and not women_shirts and not men_pants and not women_pants and not men_shoes and not women_shoes:
        hat = True
        sunglasses = True
        men_shirts = True
        women_shirts = True
        men_pants = True
        women_pants = True
        men_shoes = True
        women_shoes = True

    async with connection.begin() as session:
        if is_admin:
            products = (await session.execute(select(Product).filter_by())).all()
        else:
            products = (await session.execute(select(Product).filter_by(draft=False, archived=False))).all()
        products: List[Product] = [product[0] for product in products]
        products_filtered = []
        products_filtered2 = []
        for product in products:
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
            elif men_shirts and product.category == "men-shirts":
                products_filtered2.append(product)
            elif women_shirts and product.category == "women-shirts":
                products_filtered2.append(product)
            elif men_pants and product.category == "men-pants":
                products_filtered2.append(product)
            elif women_pants and product.category == "women-pants":
                products_filtered2.append(product)
            elif men_shoes and product.category == "men-shoes":
                products_filtered2.append(product)
            elif women_shoes and product.category == "women-shoes":
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
            "products": products_filtered2,
            "sorting_method": sort,
            "filter_active": active,
            "filter_archived": archived,
            "filter_draft": draft,
            "filter_hat": hat,
            "filter_sunglasses": sunglasses,
            "filter_men_shirts": men_shirts,
            "filter_women_shirts": women_shirts,
            "filter_men_pants": men_pants,
            "filter_women_pants": women_pants,
            "filter_men_shoes": men_shoes,
            "filter_women_shoes": women_shoes,
        }
    )

@app.post("/", response_class=HTMLResponse)
async def product_edit_post(
        sorting_method: str = Form(""),
        active: bool = Form(False),
        archived: bool = Form(False),
        draft: bool = Form(False),
        hat: bool = Form(False),
        sunglasses: bool = Form(False),
        men_shirts: bool = Form(False),
        women_shirts: bool = Form(False),
        men_pants: bool = Form(False),
        women_pants: bool = Form(False),
        men_shoes: bool = Form(False),
        women_shoes: bool = Form(False),
):
    encode = {
        "sort": sorting_method,
    }
    if active:
        encode["active"] = True
    if archived:
        encode["archived"] = True
    if draft:
        encode["draft"] = True
    if hat:
        encode["hat"] = True
    if sunglasses:
        encode["sunglasses"] = True
    if men_shirts:
        encode["men_shirts"] = True
    if women_shirts:
        encode["women_shirts"] = True
    if men_pants:
        encode["men_pants"] = True
    if women_pants:
        encode["women_pants"] = True
    if men_shoes:
        encode["men_shoes"] = True
    if women_shoes:
        encode["women_shoes"] = True
    return RedirectResponse(app.url_path_for("home") + f"?{urllib.parse.urlencode(encode)}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/about", response_class=HTMLResponse)
async def about_project(request: Request):
    user = await get_session_user(request.cookies.get("session"))
    name = f"{user.first_name} {user.surname}" if user is not None else None
    is_admin = False if user is None else user.is_admin
    return templates.TemplateResponse(
        request=request, name="about.jinja", context={"name": name, "is_admin": is_admin}
    )

@app.get("/item/{item_id}", response_class=HTMLResponse)
async def item_details(request: Request, item_id: str):
    user = await get_session_user(request.cookies.get("session"))
    name = f"{user.first_name} {user.surname}" if user is not None else None
    is_admin = False if user is None else user.is_admin
    if not is_admin:
        edit = False
    async with connection.begin() as session:
        product = (await session.execute(select(Product).filter_by(product_id=item_id))).one_or_none()
        if product is None:
            return RedirectResponse(app.url_path_for("home"))
        product = product[0]
        if (product.draft or product.archived) and not is_admin:
            return RedirectResponse(app.url_path_for("home"))
        product_images = (await session.execute(select(ProductImage).filter_by(product_id=item_id).order_by(ProductImage.position))).all()
        product_images = [product_image[0] for product_image in product_images]
    return templates.TemplateResponse(
        request=request, name="item.jinja", context={"item": None, "name": name, "is_admin": is_admin, "product": product, "product_images": product_images}
    )

@app.get("/item/{product_id}/edit", response_class=HTMLResponse)
async def product_edit(request: Request, product_id: str):
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    name = f"{user.first_name} {user.surname}" if user is not None else None
    async with connection.begin() as session:
        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if product is None:
            return RedirectResponse(app.url_path_for("home"))
        product = product[0]
        product_images = (await session.execute(select(ProductImage).filter_by(product_id=product_id).order_by(ProductImage.position))).all()
        product_images = [product_image[0] for product_image in product_images]
    return templates.TemplateResponse(
        request=request, name="product_edit.jinja", context={"name": name, "is_admin": True, "product": product, "images": product_images}
    )

@app.get("/admin/new_product", response_class=HTMLResponse)
async def new_product(request: Request):
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    name = f"{user.first_name} {user.surname}" if user is not None else None
    return templates.TemplateResponse(
        request=request, name="new_product.jinja", context={"name": name, "is_admin": True}
    )

@app.post("/admin/new_product", response_class=HTMLResponse)
async def new_product_post(request: Request, name: str = Form(""), description: str = Form(""), category: str = Form("")):
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
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
            description=description,
            category=category,
            size="",
            default_image_id="",
            archived=False,
            draft=True,
            published_by=user.user_id,
            published_at=t,
            last_edited_by=user.user_id,
            last_edited_at=t,
        )
        session.add(product)
    return RedirectResponse(app.url_path_for("product_edit", product_id=uid), status_code=status.HTTP_303_SEE_OTHER)

@app.post("/item/{product_id}/edit", response_class=HTMLResponse)
async def product_edit_post(request: Request, product_id: str, name: str = Form(""), description: str = Form(""), category: str = Form(""), size: str = Form(""), archived: bool = Form(False), draft: bool = Form(False)):
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
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
        pi.description = description
        pi.category = category
        pi.size = size
        pi.archived = archived
        pi.draft = draft
        pi.last_edited_by = user.user_id
        pi.last_edited_at = int(time.time())
    return RedirectResponse(app.url_path_for("product_edit", product_id=product_id), status_code=status.HTTP_303_SEE_OTHER)

@app.get("/item/{product_id}/delete", response_class=HTMLResponse)
async def delete_product(request: Request, product_id: str):
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
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

@app.get("/item/{product_id}/archive", response_class=HTMLResponse)
async def archive_product(request: Request, product_id: str):
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one()
        product = product[0]
        product.archived = not product.archived
        product.last_edited_by = user.user_id
        product.last_edited_at = int(time.time())
    return RedirectResponse(app.url_path_for("item_details", item_id=product_id), status_code=status.HTTP_303_SEE_OTHER)


@app.post("/item/{product_id}/upload_image")
async def upload_image(request: Request, product_id: str, file: UploadFile, description: str = Form("")):
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        uid = str(uuid.uuid4())
        contents = await file.read()
        img = Image.open(io.BytesIO(contents))
        img.save(f"uploads/images/{uid}.png", optimize=True, quality=80)
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

@app.get("/image/{image_id}/delete")
async def delete_image(request: Request, image_id: str):
    # Prvo preverimo, da ima uporabnik veljaven session in je administrator
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
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
            os.remove(f"uploads/images/{image_id}.png")
        except:
            pass

    return RedirectResponse(app.url_path_for("product_edit", product_id=product_id), status_code=status.HTTP_303_SEE_OTHER)


@app.get("/image/{image_id}/move/{up_down}")
async def move_image_up_down(request: Request, image_id: str, up_down: str):
    # Prvo preverimo, da ima uporabnik veljaven session in je administrator
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
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
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
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


@app.get("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    redirect_response = RedirectResponse(app.url_path_for("home"))
    redirect_response.set_cookie(key="session", value="", httponly=True, secure=True)

    user = await get_session_user(request.cookies.get("session"))
    if user is None:
        return redirect_response
    async with connection.begin() as session:
        result = (await session.execute(select(User).filter_by(user_id=user.user_id))).one_or_none()
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


@app.get("/microsoft/login/url", response_class=HTMLResponse)
async def microsoft_login_redirect(request: Request):
    return RedirectResponse(
        f"https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?client_id={MICROSOFT_CLIENT_ID}&response_type=code&response_mode=query&scope={SCOPE}")


@app.get("/microsoft/login/auth", response_class=HTMLResponse)
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
                session_token=None,
                is_admin=False,
            )
        else:
            user = user[0]

        # Zgeneriramo nov session token za uporabnika, če ga še nima
        if user.session_token is None:
            user.session_token = random_session_token()

        session.add(user)

        # Pošljemo session token kot piškotek (cookie) nazaj
        redirect_response = RedirectResponse(app.url_path_for("home") + "?login_success=True")
        redirect_response.set_cookie(key="session", value=user.session_token, httponly=True, secure=True)

        # Ta session token shranimo v cache
        sessions[user.session_token] = user

        # Na koncu se vse avtomatično comitta v podatkovno bazo

    return redirect_response
