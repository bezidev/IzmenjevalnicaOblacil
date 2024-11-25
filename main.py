import io
import time
import uuid
from contextlib import asynccontextmanager

import aiofiles
import httpx
import os

from PIL import Image
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
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

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, login_success: bool | None = None):
    user = await get_session_user(request.cookies.get("session"))
    name = f"{user.first_name} {user.surname}" if user is not None else None
    is_admin = False if user is None else user.is_admin
    async with connection.begin() as session:
        products = (await session.execute(select(Product).filter_by())).all()
        products = [product[0] for product in products]
    return templates.TemplateResponse(
        request=request, name="home.jinja", context={"login_success": login_success, "name": name, "is_admin": is_admin, "products": products}
    )

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
        product_images = (await session.execute(select(ProductImage).filter_by(product_id=item_id))).all()
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
        product_images = (await session.execute(select(ProductImage).filter_by(product_id=product_id))).all()
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
    user = await get_session_user(request.cookies.get("session"))
    if user is None or not user.is_admin:
        return RedirectResponse(app.url_path_for("home"))
    async with connection.begin() as session:
        pi = (await session.execute(select(ProductImage).filter_by(image_id=image_id))).one_or_none()
        if pi is None:
            return RedirectResponse(app.url_path_for("home"))
        pi = pi[0]

        product_id = pi.product_id

        product = (await session.execute(select(Product).filter_by(product_id=product_id))).one_or_none()
        if product is None:
            return RedirectResponse(app.url_path_for("home"))
        product = product[0]

        await session.delete(pi)

        product_images = (await session.execute(select(ProductImage).filter(ProductImage.product_id == product_id and ProductImage.position >= pi.position).order_by(ProductImage.position))).all()
        product_images = [product_image[0] for product_image in product_images]
        for product_image in product_images:
            product_image.position -= 1

        if product.default_image_id == image_id:
            if len(product_images) == 0:
                product.default_image_id = ""
            else:
                product.default_image_id = product_images[0].image_id

        try:
            os.remove(f"uploads/images/{image_id}.png")
        except:
            pass

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
