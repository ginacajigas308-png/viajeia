import io
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import google.generativeai as genai
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from zoneinfo import ZoneInfo

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"

load_dotenv(dotenv_path=ENV_FILE)

app = FastAPI(title="ViajeIA API", description="Backend para el asistente de viajes")

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HistoryEntry(BaseModel):
    pregunta: str
    respuesta: Optional[str] = None
    destino: Optional[str] = None
    timestamp: str


class PlanRequest(BaseModel):
    pregunta: str
    session_id: Optional[str] = None


class PanelSection(BaseModel):
    label: str
    value: str
    description: Optional[str] = None


class PanelInfo(BaseModel):
    currency: Optional[PanelSection] = None
    time: Optional[PanelSection] = None
    weather: Optional[PanelSection] = None


class PlanResponse(BaseModel):
    respuesta: str
    fotos: List[str] = []
    panel: Optional[PanelInfo] = None
    history: List[HistoryEntry] = []
    favorites: List[str] = []


conversation_store: Dict[str, List[HistoryEntry]] = {}
favorites_store: Dict[str, List[str]] = {}


def extract_field(text: str, label: str) -> Optional[str]:
    marker = f"{label}:"
    if marker not in text:
        return None
    segmento = text.split(marker, 1)[1]
    posible = segmento.split("|", 1)[0].strip().strip(".")
    return posible or None


def extract_destino(text: str) -> Optional[str]:
    return extract_field(text, "Destino deseado")


def get_weather_data(destino: Optional[str]) -> Optional[dict]:
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key or not destino:
        return None

    params = {
        "q": destino,
        "appid": api_key,
        "units": "metric",
        "lang": "es",
    }
    try:
        response = requests.get(
            "https://api.openweathermap.org/data/2.5/weather", params=params, timeout=8
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return None

    weather = data.get("weather", [{}])[0]
    main = data.get("main", {})
    return {
        "summary": weather.get("description", "").capitalize(),
        "temperature": main.get("temp"),
        "feels_like": main.get("feels_like"),
        "humidity": main.get("humidity"),
        "wind": data.get("wind", {}).get("speed"),
        "country": data.get("sys", {}).get("country"),
        "timezone_offset": data.get("timezone"),
        "city": data.get("name") or destino,
    }


def get_destination_photos(destino: Optional[str]) -> List[str]:
    api_key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not api_key or not destino:
        return []

    params = {
        "query": destino,
        "per_page": 3,
        "orientation": "landscape",
    }
    headers = {"Accept-Version": "v1", "Authorization": f"Client-ID {api_key}"}
    try:
        response = requests.get(
            "https://api.unsplash.com/search/photos",
            params=params,
            headers=headers,
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return []

    results = data.get("results", [])
    urls = []
    for item in results:
        url = item.get("urls", {}).get("regular")
        if url:
            urls.append(url)
    return urls


def get_currency_code(country_code: Optional[str]) -> Optional[str]:
    if not country_code:
        return None
    try:
        response = requests.get(
            f"https://restcountries.com/v3.1/alpha/{country_code}",
            params={"fields": "currencies"},
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return None

    if not data:
        return None
    currencies = data[0].get("currencies")
    if not currencies:
        return None
    return next(iter(currencies.keys()))


def get_exchange_rate(target_currency: Optional[str]) -> Optional[PanelSection]:
    if not target_currency:
        return None
    base_currency = os.getenv("HOME_CURRENCY", "USD").upper()
    target_currency = target_currency.upper()
    if base_currency == target_currency:
        return PanelSection(
            label="Tipo de cambio",
            value=f"Usas {base_currency}",
            description="La moneda local coincide con tu moneda base.",
        )

    try:
        response = requests.get(
            f"https://open.er-api.com/v6/latest/{base_currency}", timeout=8
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return None

    rate = data.get("rates", {}).get(target_currency)
    if rate is None:
        return None

    return PanelSection(
        label="Tipo de cambio",
        value=f"1 {base_currency} ≈ {rate:,.2f} {target_currency}",
        description="Tasa en tiempo real cortesía de open.er-api.com",
    )


def get_time_difference_info(offset_seconds: Optional[int]) -> Optional[PanelSection]:
    if offset_seconds is None:
        return None

    home_timezone_name = os.getenv("HOME_TIMEZONE", "UTC")
    try:
        home_tz = ZoneInfo(home_timezone_name)
    except Exception:
        home_tz = timezone.utc
        home_timezone_name = "UTC"

    home_now = datetime.now(home_tz)
    home_offset = home_now.utcoffset() or timedelta(0)

    destination_tz = timezone(timedelta(seconds=offset_seconds))
    destination_now = datetime.now(destination_tz)

    diff_hours = (offset_seconds - home_offset.total_seconds()) / 3600
    sign = "+" if diff_hours >= 0 else "-"
    diff_text = f"{sign}{abs(diff_hours):.1f} h"

    description = (
        f"Destino {destination_now.strftime('%H:%M')} · tu zona "
        f"{home_now.strftime('%H:%M')} ({home_timezone_name})"
    )

    return PanelSection(
        label="Diferencia horaria",
        value=diff_text,
        description=description,
    )


def format_weather_section(weather_data: Optional[dict]) -> Optional[PanelSection]:
    if not weather_data:
        return None

    temp = weather_data.get("temperature")
    summary = weather_data.get("summary")
    feels = weather_data.get("feels_like")

    value = f"{temp:.0f} °C" if temp is not None else summary or "N/D"
    description_parts = []
    if summary:
        description_parts.append(summary)
    if feels is not None:
        description_parts.append(f"Sensación {feels:.0f} °C")
    if weather_data.get("humidity") is not None:
        description_parts.append(f"Humedad {weather_data['humidity']}%")

    description = ". ".join(description_parts) if description_parts else None

    return PanelSection(
        label="Temperatura actual",
        value=value,
        description=description,
    )


def wrap_text(text: str, width: int = 90) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = []
    current_len = 0
    for word in words:
        if current_len + len(word) + (1 if current else 0) > width:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += len(word) + (1 if current_len else 0)
    if current:
        lines.append(" ".join(current))
    return lines or [text]


def _get_gemini_model() -> genai.GenerativeModel:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Falta la variable de entorno GEMINI_API_KEY o GOOGLE_API_KEY.",
        )

    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    return genai.GenerativeModel(model_name)


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "ViajeIA backend listo"}


@app.post("/plan", response_model=PlanResponse)
async def plan_trip(payload: PlanRequest):
    session_id = payload.session_id or "anon"
    history_entries = conversation_store.get(session_id, [])

    model = _get_gemini_model()
    destino = extract_destino(payload.pregunta)
    if not destino and history_entries:
        destino = history_entries[-1].destino

    weather_data = get_weather_data(destino)
    fotos = get_destination_photos(destino)

    country_code = weather_data.get("country") if weather_data else None
    currency_code = get_currency_code(country_code)
    currency_section = get_exchange_rate(currency_code)

    timezone_offset = weather_data.get("timezone_offset") if weather_data else None
    time_section = get_time_difference_info(timezone_offset)

    weather_section = format_weather_section(weather_data)

    history_text = ""
    if history_entries:
        formatted = "\n".join(
            f"- Pregunta: {entry.pregunta}\n  Respuesta previa: {entry.respuesta}"
            for entry in history_entries[-5:]
        )
        history_text = f"\nHistorial reciente:\n{formatted}\n"

    prompt = (
        "Preséntate siempre como 'Alex, tu consultor personal de viajes'. "
        "Mantén un tono entusiasta y amigable, utiliza emojis relacionados con viajes "
        "✈️ 🌍 🧳. Antes de recomendar, incluye 1-2 preguntas para conocer mejor las "
        "preferencias (presupuesto, intereses, ritmo del viaje). "
        "La respuesta siempre debe seguir exactamente este formato (usa bullets donde aplique):\n"
        "» ALOJAMIENTO: ...\n"
        "Þ COMIDA LOCAL: ...\n"
        " LUGARES IMPERDIBLES: ...\n"
        "ä CONSEJOS LOCALES: ...\n"
        "ø ESTIMACIÓN DE COSTOS: ...\n"
        "Si falta información, solicita más detalles dentro de la sección correspondiente. "
        f"Contexto del viajero: {payload.pregunta}"
        f"{history_text}"
    )
    if weather_data and destino:
        weather_bits = []
        if weather_data.get("summary"):
            weather_bits.append(weather_data["summary"])
        if weather_data.get("temperature") is not None:
            weather_bits.append(f"{weather_data['temperature']:.0f} °C")
        if weather_data.get("humidity") is not None:
            weather_bits.append(f"Humedad {weather_data['humidity']}%")

        if weather_bits:
            prompt += (
                f"\nInformación de clima actual para {destino}: "
                + ", ".join(weather_bits)
            )

    try:
        completion = model.generate_content(
            [
                "Actúa como planificador experto en viajes.",
                prompt,
            ]
        )
        respuesta = (completion.text or "").strip()
    except Exception as exc:  # pragma: no cover - handled via HTTPException
        raise HTTPException(
            status_code=502,
            detail=f"No pudimos obtener la recomendación de Gemini: {exc}",
        ) from exc

    if not respuesta:
        respuesta = "No recibimos una respuesta clara, intenta describir un poco más tu viaje."

    panel = PanelInfo(
        currency=currency_section,
        time=time_section,
        weather=weather_section,
    )

    entry = HistoryEntry(
        pregunta=payload.pregunta,
        respuesta=respuesta,
        destino=destino,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )
    updated_history = history_entries + [entry]
    conversation_store[session_id] = updated_history[-10:]
    favorites = favorites_store.get(session_id, [])

    return {
        "respuesta": respuesta,
        "fotos": fotos,
        "panel": panel,
        "history": conversation_store[session_id],
        "favorites": favorites,
    }


class FavoriteRequest(BaseModel):
    session_id: str
    destino: str


class FavoritesResponse(BaseModel):
    favorites: List[str]


@app.get("/favorites", response_model=FavoritesResponse)
async def list_favorites(session_id: str):
    favorites = favorites_store.get(session_id, [])
    return FavoritesResponse(favorites=favorites)


@app.post("/favorites", response_model=FavoritesResponse)
async def save_favorite(payload: FavoriteRequest):
    session_id = payload.session_id.strip()
    destino = payload.destino.strip()

    if not session_id or not destino:
        raise HTTPException(status_code=400, detail="session_id y destino son obligatorios.")

    favorites = favorites_store.setdefault(session_id, [])
    if destino not in favorites:
        favorites.append(destino)

    return FavoritesResponse(favorites=favorites)


@app.get("/itinerary/pdf")
async def download_itinerary(session_id: str):
    history = conversation_store.get(session_id)
    if not history:
        raise HTTPException(
            status_code=404,
            detail="No encontramos una conversación activa para generar el PDF.",
        )

    latest = history[-1]
    destino = latest.destino or extract_destino(latest.pregunta) or "Destino no especificado"
    fechas = extract_field(latest.pregunta, "Fechas aproximadas") or "Fechas no definidas"

    photos = get_destination_photos(destino)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    def draw_header():
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(40, height - 60, "ViajeIA")
        pdf.setFont("Helvetica", 12)
        pdf.drawString(40, height - 80, "Alex, tu consultor personal de viajes")
        pdf.line(40, height - 90, width - 40, height - 90)

    draw_header()
    y = height - 120
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, f"Destino: {destino}")
    y -= 20
    pdf.drawString(40, y, f"Fechas: {fechas}")
    y -= 30

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(40, y, "Resumen de la conversación")
    y -= 16

    text = pdf.beginText(40, y)
    text.setFont("Helvetica", 11)
    for entry in history:
        text.textLine(f"• Pregunta: {entry.pregunta}")
        if entry.respuesta:
            for line in wrap_text(entry.respuesta):
                text.textLine(f"  {line}")
        text.textLine("")
        if text.getY() < 80:
            pdf.drawText(text)
            pdf.showPage()
            draw_header()
            y = height - 120
            pdf.setFont("Helvetica-Bold", 13)
            pdf.drawString(40, y, "Resumen de la conversación (cont.)")
            y -= 16
            text = pdf.beginText(40, y)
            text.setFont("Helvetica", 11)
    pdf.drawText(text)

    if photos:
        pdf.showPage()
        draw_header()
        pdf.setFont("Helvetica-Bold", 13)
        pdf.drawString(40, height - 120, "Inspiración visual")
        x_positions = [40, width / 2 - 90, width - 220]
        y_photo = height - 320
        for idx, url in enumerate(photos[:3]):
            try:
                image_data = requests.get(url, timeout=8).content
                img = ImageReader(io.BytesIO(image_data))
                pdf.drawImage(img, x_positions[idx], y_photo, width=180, height=160, preserveAspectRatio=True, mask='auto')
            except Exception:
                continue

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    filename = f"viajeia-itinerario-{session_id[:8]}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    if not FRONTEND_DIST.exists():
        raise HTTPException(
            status_code=503,
            detail="Build de frontend no encontrado. Ejecuta `npm run build` en frontend.",
        )

    index_file = FRONTEND_DIST / "index.html"
    return HTMLResponse(index_file.read_text(encoding="utf-8"))
