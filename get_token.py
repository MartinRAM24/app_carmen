# oauth_get_token.py  (Python 3.12 recomendado)
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
import json

SCOPES = ["https://www.googleapis.com/auth/drive"]
CLIENT_FILE = "client_secret.json"
OUT = Path("token.json")

def main():
    if not Path(CLIENT_FILE).exists():
        raise FileNotFoundError(
            f"No encuentro {CLIENT_FILE}. Descárgalo desde Google Cloud (Desktop app) y colócalo aquí."
        )

    # Elegimos puerto aleatorio disponible; la librería añade la redirect URI correcta (http://localhost:<puerto>/)
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_FILE, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        raise RuntimeError(
            "No recibí refresh_token. Borra el acceso previo en https://myaccount.google.com/permissions "
            "y vuelve a autorizar."
        )

    data = {
        "client_id": flow.client_config["client_id"],
        "client_secret": flow.client_config["client_secret"],
        "refresh_token": creds.refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": SCOPES,
    }
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("\n✅ Listo, guardado en token.json")
    print("\nPega en tus secrets de Streamlit:")
    print(
        "\n[google_oauth]\n"
        f"client_id = \"{data['client_id']}\"\n"
        f"client_secret = \"{data['client_secret']}\"\n"
        f"refresh_token = \"{data['refresh_token']}\"\n"
    )

if __name__ == "__main__":
    main()
