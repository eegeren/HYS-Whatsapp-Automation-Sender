#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, time, csv, re, sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

CONTACTS = os.environ.get("CONTACTS_CSV", "contacts.csv")
MESSAGE_TMPL = os.environ.get("MESSAGE", "Merhaba {name}, kampanyamız ektedir: https://SENIN-LINKIN/brosur.pdf")
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT","50"))
IGNORE_WINDOW = True
START_INDEX = int(os.environ.get("START_INDEX","0"))

def e164_tr(s):
    if s is None: return ""
    p = re.sub(r"[^\d+]", "", str(s))
    if not p: return ""
    if p.startswith("+"): return p
    if p.startswith("00"): return "+" + p[2:]
    if p.startswith("0"):  return "+90" + p[1:]
    if p.startswith("90"): return "+" + p
    return "+90" + p

def load_contacts(path):
    rows=[]
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row: continue
            if row[0].strip().lower() in ("name","isim","ad"):
                continue
            name = row[0].strip()
            phone = e164_tr(row[1] if len(row)>1 else "")
            if phone: rows.append((name, phone))
    return rows

def ensure_login(driver, wait):
    driver.get("https://web.whatsapp.com/")
    for _ in range(180):
        if driver.find_elements(By.CSS_SELECTOR, "div[role='textbox'][contenteditable='true']"):
            return True
        time.sleep(1)
    return False

def open_chat(driver, wait, to):
    driver.get(f"https://web.whatsapp.com/send?phone={to.lstrip('+')}")
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,"div[role='textbox'][contenteditable='true']")))
        return True
    except Exception:
        return False

def send_text(driver, wait, text):
    box = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#main footer div[contenteditable='true'][data-tab]"))
    )
    try: box.click()
    except: driver.execute_script("arguments[0].click();", box)
    try: box.send_keys(Keys.COMMAND, 'a')
    except: 
        try: box.send_keys(Keys.CONTROL, 'a')
        except: pass
    box.send_keys(Keys.BACKSPACE)
    box.send_keys(text)
    box.send_keys(Keys.ENTER)
    return True

def main():
    contacts = load_contacts(CONTACTS)
    if not contacts:
        print("contacts.csv boş veya format hatalı"); sys.exit(1)

    options=Options()
    options.add_argument("--window-size=1280,900")
    options.add_argument(f"--user-data-dir={os.path.abspath('./.chrome-profile')}")
    driver=webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    wait=WebDriverWait(driver, 40)

    if not ensure_login(driver, wait):
        print("WhatsApp Web’e login olmadı (QR taratılmadı).")
        driver.quit(); sys.exit(1)

    sent = 0
    for i, (name, phone) in enumerate(contacts[START_INDEX:], start=START_INDEX):
        if sent >= DAILY_LIMIT: 
            print("Günlük limit bitti."); break
        print(f"[{i}] → {phone} | {name}")
        if not open_chat(driver, wait, phone):
            print(f"[{i}] ✗ sohbet açılamadı"); continue
        msg = MESSAGE_TMPL.format(name=name)
        try:
            send_text(driver, wait, msg)
            sent += 1
            print(f"[{i}] ✓ Mesaj gönderildi (toplam: {sent}/{DAILY_LIMIT})")
        except Exception as e:
            print(f"[{i}] ✗ Hata: {e}")
        time.sleep(1)

    driver.quit()
    print("Bitti.")

if __name__ == "__main__":
    main()