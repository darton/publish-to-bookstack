#!/usr/bin/env python3
# /// script
# dependencies = [
#     "httpx",
# ]
# ///

import os
import sys
from pathlib import Path
from datetime import datetime
import httpx

# --- KONFIGURACJA ZE ZMIENNYCH ŚRODOWISKOWYCH ---
IP_LIST_PATH = Path(os.getenv("IP_LIST_PATH", "/var/www/html/ip_list.txt"))
TXT_DIR = Path(os.getenv("TXT_DIR", "/var/www/html/txt_files"))

BOOK_NAME = os.getenv("BOOK_NAME", "LISTA IP")
BOOK_DESCRIPTION = os.getenv("BOOK_DESCRIPTION", "Automatycznie generowane raporty ze skanowania adresów IP.")
# -----------------------------------------------

BOOKSTACK_URL = os.getenv("BOOKSTACK_URL")
TOKEN_ID = os.getenv("BOOKSTACK_TOKEN_ID")
TOKEN_SECRET = os.getenv("BOOKSTACK_TOKEN_SECRET")

if not all([BOOKSTACK_URL, TOKEN_ID, TOKEN_SECRET]):
    print("Błąd: Brak wymaganych zmiennych środowiskowych (BOOKSTACK_URL, BOOKSTACK_TOKEN_ID, BOOKSTACK_TOKEN_SECRET).", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": f"Token {TOKEN_ID}:{TOKEN_SECRET}",
    "Content-Type": "application/json",
}

def get_or_create_book(client: httpx.Client, book_name: str) -> int:
    """Sprawdza czy książka istnieje, a jeśli nie - tworzy ją i zwraca jej ID."""
    response = client.get(f"{BOOKSTACK_URL}/api/books", headers=HEADERS)
    if response.status_code == 200:
        for book in response.json().get("data", []):
            if book["name"] == book_name:
                print(f"Znaleziono istniejącą książkę: '{book_name}' (ID: {book['id']})")
                return book["id"]
    
    print(f"Książka '{book_name}' nie istnieje. Tworzę nową...")
    response = client.post(
        f"{BOOKSTACK_URL}/api/books",
        headers=HEADERS,
        json={"name": book_name, "description": BOOK_DESCRIPTION}
    )
    
    if response.status_code in (200, 201):
        new_book = response.json()
        print(f"Sukces! Utworzono nową książkę (ID: {new_book['id']})")
        return new_book["id"]
    else:
        print(f"Błąd: Nie udało się utworzyć książki: {response.status_code} - {response.text}", file=sys.stderr)
        sys.exit(1)

def get_book_pages_map(client: httpx.Client, book_id: int) -> dict:
    """Pobiera mapę istniejących stron w książce: { 'adres_ip': page_id }"""
    response = client.get(f"{BOOKSTACK_URL}/api/books/{book_id}", headers=HEADERS)
    if response.status_code != 200:
        print(f"Ostrzeżenie: Nie udało się pobrać zawartości książki ({response.status_code})")
        return {}

    book_data = response.json()
    contents = book_data.get("contents", [])
    
    pages_map = {}
    
    def extract_pages(items):
        for item in items:
            if item.get("type") == "page":
                pages_map[item["name"]] = item["id"]
            elif item.get("type") == "chapter" and "pages" in item:
                for p in item["pages"]:
                    pages_map[p["name"]] = p["id"]
                    
    extract_pages(contents)
    return pages_map

def main():
    if not IP_LIST_PATH.exists():
        print(f"Błąd: Nie znaleziono pliku z listą IP: {IP_LIST_PATH}", file=sys.stderr)
        sys.exit(1)

    ips = [line.strip() for line in IP_LIST_PATH.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]

    with httpx.Client(timeout=30.0) as client:
        # 1. Pobierz lub utwórz książkę
        book_id = get_or_create_book(client, BOOK_NAME)

        # 2. Pobierz słownik już istniejących stron w tej książce {nazwa_ip: id_strony}
        existing_pages = get_book_pages_map(client, book_id)
        print(f"W książce znajduje się obecnie {len(existing_pages)} stron.")

        current_date = datetime.now().strftime("%Y-%m-%d %H:%M")
        print("Rozpoczynam synchronizację raportów...")

        for ip in ips:
            file_path = TXT_DIR / f"{ip}.txt"
            
            if not file_path.is_file():
                print(f"Pomijam {ip}: Brak pliku raportu.")
                continue

            file_content = file_path.read_text(encoding="utf-8", errors="ignore")
            lines = file_content.splitlines()
            
            table_lines = []
            parsing_table = False
            
            for line in lines:
                if "RAPORT" in line.upper() or ("=" in line and "PAKIET" not in line):
                    continue
                if "PAKIET" in line and "ARCHITEKTURA" in line:
                    parsing_table = True
                    headers = [h.strip() for h in line.split("|") if h.strip()]
                    table_lines.append("| " + " | ".join(headers) + " |")
                    table_lines.append("|" + "|".join(["---"] * len(headers)) + "|")
                    continue
                if set(line.strip()) <= {"-", " "}:
                    continue
                if parsing_table and "|" in line:
                    cols = [c.strip() for c in line.split("|") if c.strip()]
                    if cols:
                        table_lines.append("| " + " | ".join(cols) + " |")

            if table_lines:
                intro_snippet = f"📅 Data ostatniej aktualizacji: {current_date}\n\n"
                markdown_content = intro_snippet + "\n".join(table_lines)
            else:
                markdown_content = f"```text\n{file_content}\n```"

            page_data = {
                "book_id": book_id,
                "name": ip,
                "markdown": markdown_content
            }

            # 3. UPSERT: Jeśli strona o tym IP już istnieje -> aktualizuj (PUT), w przeciwnym razie -> utwórz (POST)
            if ip in existing_pages:
                page_id = existing_pages[ip]
                response = client.put(f"{BOOKSTACK_URL}/api/pages/{page_id}", headers=HEADERS, json=page_data)
                action = "Zaktualizowano"
            else:
                response = client.post(f"{BOOKSTACK_URL}/api/pages", headers=HEADERS, json=page_data)
                action = "Utworzono"

            if response.status_code in (200, 201):
                print(f"[SUKCES] {action} stronę dla IP: {ip}")
            else:
                print(f"[BŁĄD] Nie udało się zapisać IP {ip}: {response.status_code} - {response.text}")

if __name__ == "__main__":
    main()
