#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhatsApp Web PDF Gönderim Otomasyonu - macOS
Kişilere otomatik olarak PDF dosyası gönderir
"""

import os
import sys
import time
import csv
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# .env dosyasını yükle
load_dotenv()

class WhatsAppSender:
    def __init__(self, pdf_path, contacts_file):
        self.pdf_path = Path(pdf_path).expanduser().resolve()
        self.contacts_file = contacts_file
        self.driver = None
        self.cached_file_input = None
        self.sent_count = 0
        self.failed_contacts = []
        
        # Ayarlar
        self.MESSAGE = os.getenv('MESSAGE', '')
        self.INTERVAL_SECONDS = float(os.getenv('INTERVAL_SECONDS', '3'))
        self.DAILY_LIMIT = int(os.getenv('DAILY_LIMIT', '100'))
        self.ATTACH_RETRIES = int(os.getenv('ATTACH_RETRIES', '3'))
        self.SEND_RETRIES = int(os.getenv('SEND_RETRIES', '3'))
        self.PREVIEW_TIMEOUT = float(os.getenv('PREVIEW_TIMEOUT', '10'))
        self.FORCE_DIALOG_MODE = os.getenv('FORCE_DIALOG_MODE', 'false').lower() == 'true'
        self.MAC_DIALOG_FALLBACK = os.getenv('MAC_DIALOG_FALLBACK', 'true').lower() == 'true'
        self.WAIT_SECS = float(os.getenv('WAIT_SECS', '0.1'))
        self.AUTO_CLOSE_FINDER = os.getenv('AUTO_CLOSE_FINDER', 'true').lower() == 'true'
        
        # PDF kontrolü
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF dosyası bulunamadı: {self.pdf_path}")
        
        print(f"📄 PDF: {self.pdf_path}")
        print(f"⚙️  Ayarlar: interval={self.INTERVAL_SECONDS}s, limit={self.DAILY_LIMIT}, retries={self.ATTACH_RETRIES}/{self.SEND_RETRIES}")
        
    def init_driver(self):
        """Chrome sürücüsünü başlat"""
        print("🌐 Chrome başlatılıyor...")
        options = webdriver.ChromeOptions()
        options.add_argument('--user-data-dir=/tmp/whatsapp_session')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.page_load_strategy = 'eager'
        
        self.driver = webdriver.Chrome(options=options)
        self.driver.get('https://web.whatsapp.com')
        
        print("📱 QR kod ile giriş yapın...")
        self.wait_for_login()
        
    def wait_for_login(self):
        """WhatsApp'a giriş yapılmasını bekle"""
        print("⏳ WhatsApp yükleniyor...")
        time.sleep(3)
        
        # Önce QR kod var mı kontrol et
        max_wait = 120
        login_detected = False
        
        for i in range(int(max_wait / 2)):
            try:
                # QR kod hala var mı?
                qr = self.driver.find_elements(By.CSS_SELECTOR, 'canvas[aria-label*="QR"]')
                if qr and qr[0].is_displayed():
                    if not login_detected:
                        print("📱 QR kodu telefonunuzla tarayın...")
                        login_detected = True
                
                # Chat listesi göründü mü?
                chat_list = self.driver.find_elements(By.CSS_SELECTOR, '[data-testid="chat-list"]')
                if chat_list:
                    print("✓ WhatsApp'a giriş yapıldı")
                    time.sleep(3)
                    return True
                
                # Alternatif selector'lar
                side_panel = self.driver.find_elements(By.ID, 'side')
                pane_side = self.driver.find_elements(By.CSS_SELECTOR, '[data-testid="chatlist-header"]')
                
                if side_panel or pane_side:
                    print("✓ WhatsApp'a giriş yapıldı")
                    time.sleep(3)
                    return True
                    
            except Exception as e:
                print(f"DEBUG: Login check error: {e}")
            
            time.sleep(2)
        
        print("❌ Giriş zaman aşımı - WhatsApp açık görünmüyor")
        print("💡 Manuel olarak giriş yapın ve devam etmek için ENTER'a basın...")
        input()
        return True
            
    def load_contacts(self):
        """Kişileri CSV'den yükle"""
        contacts = []
        with open(self.contacts_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('name', '').strip()
                phone = row.get('phone', '').strip().replace('+', '').replace(' ', '')
                if name and phone:
                    contacts.append({'name': name, 'phone': phone})
        print(f"📋 {len(contacts)} kişi yüklendi")
        return contacts
    
    def open_chat(self, phone):
        """Kişi sohbetini aç"""
        url = f"https://web.whatsapp.com/send?phone={phone}"
        print(f"DEBUG: Açılıyor: {url}")
        self.driver.get(url)
        
        # Sayfa yüklenmesini bekle
        time.sleep(3)
        
        # Geçersiz numara kontrolü
        invalid_selectors = [
            '[data-testid="invalid-phone"]',
            'div[role="button"]:has-text("OK")',
            'div:contains("Telefon numarası")'
        ]
        
        for selector in invalid_selectors:
            try:
                elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                if elem.is_displayed():
                    print("⚠️  Geçersiz numara!")
                    return False
            except:
                pass
        
        # Sohbet kutusu kontrolü - birden fazla selector dene
        chat_selectors = [
            '[data-testid="conversation-compose-box-input"]',
            '[contenteditable="true"][data-tab="10"]',
            'div[contenteditable="true"][role="textbox"]',
            'footer div[contenteditable="true"]'
        ]
        
        max_wait = 15
        for i in range(int(max_wait / self.WAIT_SECS)):
            for selector in chat_selectors:
                try:
                    elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if elem.is_displayed():
                        print(f"DEBUG: ✓ Sohbet kutusu bulundu ({selector})")
                        time.sleep(1)
                        return True
                except:
                    pass
            time.sleep(self.WAIT_SECS)
        
        print("⚠️  Sohbet kutusu bulunamadı - Manuel kontrol...")
        print("💡 Sohbet açıksa ENTER'a basın, yoksa 'n' yazıp ENTER...")
        response = input().strip().lower()
        return response != 'n'
    
    def find_file_input(self):
        """PDF input elementini bul"""
        if self.cached_file_input and not self.FORCE_DIALOG_MODE:
            try:
                # Cache'li input hala geçerli mi?
                self.cached_file_input.is_enabled()
                print("DEBUG INPUTS: Cache'den kullanılıyor")
                return self.cached_file_input
            except:
                self.cached_file_input = None
        
        print("DEBUG INPUTS: File input aranıyor...")
        selectors = [
            'input[type="file"][accept*="application/pdf"]',
            'input[type="file"][accept*="*"]',
            'input[type="file"]'
        ]
        
        for selector in selectors:
            try:
                inputs = self.driver.find_elements(By.CSS_SELECTOR, selector)
                print(f"DEBUG INPUTS: {selector} → {len(inputs)} element")
                for inp in inputs:
                    if inp.is_displayed() or True:  # Gizli olsa bile dene
                        self.cached_file_input = inp
                        print(f"DEBUG INPUTS: ✓ Bulundu: {selector}")
                        return inp
            except Exception as e:
                print(f"DEBUG INPUTS: Hata ({selector}): {e}")
        
        return None
    
    def use_mac_dialog(self):
        """macOS dosya seçim diyaloğunu AppleScript ile kontrol et"""
        print("DEBUG ATTACH: macOS dialog modu aktif")
        
        # PDF seçimi ve gönderimi
        applescript = f'''
        tell application "System Events"
            delay 1
            keystroke "g" using {{command down, shift down}}
            delay 1
            keystroke "{str(self.pdf_path)}"
            delay 0.5
            keystroke return
            delay 0.8
            keystroke return
            delay 0.3
        end tell
        '''
        
        try:
            subprocess.run(['osascript', '-e', applescript], check=True, timeout=15)
            print("DEBUG ATTACH: ✓ PDF seçildi ve gönderildi")
            
            # FINDER KAPATMA - BASİT VE ETKİLİ
            if self.AUTO_CLOSE_FINDER:
                print("\n" + "="*50)
                print("🔴 FINDER AÇIK - LÜTFEN KAPATIN")
                print("="*50)
                print("1. Finder penceresine tıklayın")
                print("2. Cmd+W (veya kırmızı X) ile kapatın")
                print("3. Enter'a basın")
                print("="*50)
                input(">> Finder'ı kapattıktan sonra ENTER'a basın: ")
                print("✓ Devam ediliyor...\n")
            
            # Chrome'a geri dön
            time.sleep(0.3)
            focus_chrome = '''
            tell application "Google Chrome"
                activate
            end tell
            '''
            try:
                subprocess.run(['osascript', '-e', focus_chrome], timeout=2)
                print("DEBUG ATTACH: ✓ Chrome aktif")
            except:
                pass
            
            return True
        except Exception as e:
            print(f"DEBUG ATTACH: AppleScript hatası: {e}")
            return False
    
    def attach_pdf(self):
        """PDF'yi ekle"""
        for attempt in range(self.ATTACH_RETRIES):
            print(f"DEBUG ATTACH: Deneme {attempt + 1}/{self.ATTACH_RETRIES}")
            
            # Önce sayfanın tamamen yüklendiğinden emin ol
            time.sleep(1)
            
            # Ekleme butonunu bul ve tıkla - GENİŞLETİLMİŞ SELECTOR LİSTESİ
            attach_selectors = [
                # Yeni WhatsApp Web selector'ları
                'div[aria-label="Ekle"]',
                'div[aria-label="Attach"]',
                'div[title="Ekle"]',
                'div[title="Attach"]',
                'button[aria-label="Ekle"]',
                'button[aria-label="Attach"]',
                # Eski selector'lar
                '[data-testid="clip"]',
                '[data-icon="clip"]',
                'span[data-icon="clip"]',
                # Plus icon'u direkt ara
                'div[role="button"] span[data-icon="plus"]',
                'button span[data-icon="plus"]',
                # Genel aramalar
                'span[data-icon="attach-menu-plus"]',
                'div[aria-label*="ttach"]',
                'button[aria-label*="ttach"]'
            ]
            
            # Tüm butonları listele (debug için)
            if attempt == 0:
                try:
                    all_buttons = self.driver.find_elements(By.CSS_SELECTOR, 'button, div[role="button"]')
                    print(f"DEBUG ATTACH: Sayfada {len(all_buttons)} buton bulundu")
                    
                    # Aria-label'ları kontrol et
                    for btn in all_buttons[:20]:  # İlk 20 buton
                        aria_label = btn.get_attribute('aria-label')
                        title = btn.get_attribute('title')
                        if aria_label or title:
                            print(f"DEBUG ATTACH: Buton: aria-label='{aria_label}', title='{title}'")
                except Exception as e:
                    print(f"DEBUG ATTACH: Buton listesi alınamadı: {e}")
            
            clicked = False
            for selector in attach_selectors:
                try:
                    # Önce elementi bul
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    
                    if elements:
                        print(f"DEBUG ATTACH: '{selector}' ile {len(elements)} element bulundu")
                        
                        for elem in elements:
                            try:
                                # Element görünür mü?
                                if elem.is_displayed():
                                    # Tıklanabilir mi?
                                    elem.click()
                                    print(f"DEBUG ATTACH: ✓ Ekle butonu tıklandı ({selector})")
                                    time.sleep(1.5)
                                    clicked = True
                                    break
                            except Exception as e:
                                print(f"DEBUG ATTACH: Element tıklanamadı: {e}")
                                continue
                    
                    if clicked:
                        break
                        
                except Exception as e:
                    print(f"DEBUG ATTACH: Selector hatası ({selector}): {e}")
                    continue
            
            if not clicked:
                print("DEBUG ATTACH: ⚠️  Hiçbir ekle butonu bulunamadı")
                
                # Son çare: JavaScript ile tıklama
                try:
                    print("DEBUG ATTACH: JavaScript ile deneniyor...")
                    js_script = """
                    const buttons = document.querySelectorAll('button, div[role="button"]');
                    for (let btn of buttons) {
                        const label = btn.getAttribute('aria-label') || btn.getAttribute('title') || '';
                        if (label.toLowerCase().includes('ekle') || 
                            label.toLowerCase().includes('attach') ||
                            btn.querySelector('span[data-icon*="plus"]') ||
                            btn.querySelector('span[data-icon*="clip"]')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                    """
                    result = self.driver.execute_script(js_script)
                    if result:
                        print("DEBUG ATTACH: ✓ JavaScript ile buton tıklandı")
                        time.sleep(1.5)
                        clicked = True
                    else:
                        print("DEBUG ATTACH: JavaScript ile de bulunamadı")
                except Exception as e:
                    print(f"DEBUG ATTACH: JavaScript hatası: {e}")
                
                if not clicked:
                    if attempt < self.ATTACH_RETRIES - 1:
                        time.sleep(2)
                        continue
                    else:
                        print("💡 Manuel olarak + (Ekle) butonuna tıklayın ve ENTER'a basın...")
                        input()
                        clicked = True
            
            # Menü açıldıysa Belge seçeneğine tıkla
            if clicked:
                time.sleep(1)
                doc_selectors = [
                    # Belge butonu selector'ları
                    'li[aria-label="Belge"]',
                    'li[aria-label="Document"]',
                    'button[aria-label="Belge"]',
                    'button[aria-label="Document"]',
                    'li:has(span[data-icon="document"])',
                    'button:has(span[data-icon="document"])',
                    '[data-testid="attach-document"]',
                    # Genel arama
                    'li[role="button"]:has-text("Belge")',
                    'div[role="button"]:contains("Document")'
                ]
                
                doc_clicked = False
                for selector in doc_selectors:
                    try:
                        doc_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        
                        if doc_elements:
                            print(f"DEBUG ATTACH: '{selector}' ile {len(doc_elements)} belge elementi bulundu")
                            
                            for doc_elem in doc_elements:
                                # File input değilse tıkla
                                if doc_elem.tag_name != 'input' and doc_elem.get_attribute('type') != 'file':
                                    try:
                                        doc_elem.click()
                                        print(f"DEBUG ATTACH: ✓ Belge seçeneği tıklandı")
                                        time.sleep(1)
                                        doc_clicked = True
                                        break
                                    except:
                                        continue
                        
                        if doc_clicked:
                            break
                            
                    except Exception as e:
                        print(f"DEBUG ATTACH: Belge selector hatası: {e}")
                        continue
                
                # Belge butonunu JavaScript ile bul
                if not doc_clicked:
                    try:
                        print("DEBUG ATTACH: Belge butonu JavaScript ile aranıyor...")
                        js_script = """
                        const items = document.querySelectorAll('li[role="button"], button, div[role="button"]');
                        for (let item of items) {
                            const label = item.getAttribute('aria-label') || item.textContent || '';
                            if (label.toLowerCase().includes('belge') || 
                                label.toLowerCase().includes('document') ||
                                item.querySelector('span[data-icon="document"]')) {
                                item.click();
                                return true;
                            }
                        }
                        return false;
                        """
                        result = self.driver.execute_script(js_script)
                        if result:
                            print("DEBUG ATTACH: ✓ Belge JavaScript ile tıklandı")
                            time.sleep(1)
                            doc_clicked = True
                    except Exception as e:
                        print(f"DEBUG ATTACH: JavaScript belge hatası: {e}")
            
            # Input ile göndermeyi dene
            if not self.FORCE_DIALOG_MODE:
                file_input = self.find_file_input()
                if file_input:
                    try:
                        file_input.send_keys(str(self.pdf_path))
                        print("DEBUG ATTACH: ✓ PDF send_keys ile yüklendi")
                        time.sleep(2)
                        return True
                    except Exception as e:
                        print(f"DEBUG ATTACH: send_keys hatası: {e}")
            
            # macOS dialog fallback
            if self.MAC_DIALOG_FALLBACK or self.FORCE_DIALOG_MODE:
                print("DEBUG ATTACH: macOS dialog deneniyor...")
                if self.use_mac_dialog():
                    time.sleep(2)
                    # Önizleme var mı kontrol et
                    try:
                        preview = self.driver.find_element(By.CSS_SELECTOR, '[data-testid="media-viewer"]')
                        if preview:
                            print("DEBUG ATTACH: ✓ PDF yüklendi (dialog)")
                            return True
                    except:
                        pass
            
            if attempt < self.ATTACH_RETRIES - 1:
                print("DEBUG ATTACH: Yeniden deneniyor...")
                time.sleep(2)
        
        print("💡 PDF'yi manuel olarak seçin ve ENTER'a basın...")
        input()
        return True
    
    def wait_for_preview(self):
        """Önizleme ekranını bekle"""
        print("DEBUG: Önizleme bekleniyor...")
        start = time.time()
        
        preview_selectors = [
            '[data-testid="media-viewer"]',
            '[data-testid="media-caption-input-container"]',
            'div[role="dialog"]:has(span[data-icon="send"])',
            'div.media-viewer',
            '[data-testid="send-button"]'
        ]
        
        while time.time() - start < self.PREVIEW_TIMEOUT:
            for selector in preview_selectors:
                try:
                    preview = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if preview.is_displayed():
                        print(f"DEBUG: ✓ Önizleme algılandı ({selector})")
                        return True
                except NoSuchElementException:
                    pass
            time.sleep(self.WAIT_SECS)
        
        print("DEBUG: Önizleme bulunamadı, devam ediliyor")
        return False
    
    def click_send_button(self):
        """Gönder butonuna tıkla"""
        send_selectors = [
            '[data-testid="media-preview-send"]',
            '[aria-label*="Gönder"]',
            '[aria-label*="Send"]',
            '[data-icon="send"]',
            'button span[data-icon="send"]'
        ]
        
        for selector in send_selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    print(f"DEBUG SENDTRY: ✓ Buton tıklandı ({selector})")
                    return True
            except:
                pass
        
        return False
    
    def send_pdf(self):
        """PDF'yi gönder"""
        initial_count = self.count_sent_messages()
        print(f"DEBUG SENDTRY: Başlangıç mesaj sayısı: {initial_count}")
        
        for attempt in range(self.SEND_RETRIES):
            print(f"DEBUG SENDTRY: Gönderim {attempt + 1}/{self.SEND_RETRIES}")
            
            # Önizleme ekranını bekle
            preview_found = self.wait_for_preview()
            time.sleep(1)
            
            # Gönder butonuna tıkla
            send_clicked = self.click_send_button()
            
            if send_clicked:
                print("DEBUG SENDTRY: Gönder butonu tıklandı, bekleniyor...")
                time.sleep(3)
            else:
                # Fallback: ENTER tuşu
                print("DEBUG SENDTRY: Buton bulunamadı, ENTER deneniyor")
                try:
                    # Önce body'ye fokus
                    body = self.driver.find_element(By.TAG_NAME, 'body')
                    body.send_keys(Keys.ENTER)
                    time.sleep(0.5)
                    body.send_keys(Keys.ENTER)
                    time.sleep(3)
                except Exception as e:
                    print(f"DEBUG SENDTRY: ENTER hatası: {e}")
            
            # Gönderim kontrolü - daha detaylı
            for check in range(5):  # 5 kez kontrol et
                time.sleep(1)
                new_count = self.count_sent_messages()
                print(f"DEBUG SENDTRY: Mesaj kontrolü {check + 1}/5 - Önceki: {initial_count}, Şimdi: {new_count}")
                
                if new_count > initial_count:
                    print("✓ PDF gönderildi")
                    return True
                
                # PDF bubble kontrolü (alternatif)
                try:
                    pdf_messages = self.driver.find_elements(By.CSS_SELECTOR, 
                        'div[data-testid="msg-container"].message-out div[data-testid="media-document"]')
                    print(f"DEBUG SENDTRY: {len(pdf_messages)} PDF mesajı bulundu")
                    
                    if pdf_messages and len(pdf_messages) > 0:
                        # Son mesaj timestamp'ini kontrol et
                        last_msg = pdf_messages[-1]
                        # Eğer son mesaj çok yeni ise gönderilmiştir
                        print("DEBUG SENDTRY: ✓ PDF mesajı DOM'da bulundu")
                        return True
                except Exception as e:
                    print(f"DEBUG SENDTRY: PDF bubble kontrolü hatası: {e}")
            
            if attempt < self.SEND_RETRIES - 1:
                print("DEBUG SENDTRY: Gönderim algılanamadı, yeniden deneniyor...")
                time.sleep(2)
        
        # Son kontrol
        final_count = self.count_sent_messages()
        print(f"DEBUG SENDTRY: Final kontrol - Başlangıç: {initial_count}, Son: {final_count}")
        
        if final_count > initial_count:
            print("✓ PDF gönderildi (gecikmiş algılama)")
            return True
        
        # Manuel onay
        print("⚠️  Gönderim otomatik algılanamadı")
        print("💡 PDF gönderildiyse 'y' yazıp ENTER, gönderilmediyse sadece ENTER basın:")
        response = input().strip().lower()
        return response == 'y'
    
    def count_sent_messages(self):
        """Gönderilen mesaj sayısını say"""
        try:
            # Farklı selector'lar dene
            selectors = [
                '[data-testid="msg-container"].message-out',
                'div.message-out',
                'div[data-testid="msg-container"][class*="message-out"]'
            ]
            
            for selector in selectors:
                try:
                    msgs = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if msgs:
                        return len(msgs)
                except:
                    continue
            
            return 0
        except Exception as e:
            print(f"DEBUG: Mesaj sayma hatası: {e}")
            return 0
    
    def send_text_message(self, name):
        """Metin mesajı gönder"""
        if not self.MESSAGE:
            print("DEBUG MESSAGE: Mesaj ayarı boş, atlanıyor")
            return True
        
        try:
            message = self.MESSAGE.replace('{name}', name)
            print(f"DEBUG MESSAGE: Hedef mesaj: '{message}'")
            
            # Önce sayfanın hazır olduğundan emin ol
            time.sleep(1)
            
            # Mesaj kutusunu bul - daha agresif
            compose_selectors = [
                '[data-testid="conversation-compose-box-input"]',
                '[contenteditable="true"][data-tab="10"]',
                'div[contenteditable="true"][role="textbox"]',
                'footer div[contenteditable="true"]',
                'div[contenteditable="true"]'
            ]
            
            compose = None
            for selector in compose_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    print(f"DEBUG MESSAGE: '{selector}' → {len(elements)} element")
                    
                    for elem in elements:
                        if elem.is_displayed():
                            compose = elem
                            print(f"DEBUG MESSAGE: ✓ Mesaj kutusu bulundu ({selector})")
                            break
                    
                    if compose:
                        break
                except Exception as e:
                    print(f"DEBUG MESSAGE: Selector hatası: {e}")
                    continue
            
            if not compose:
                print("⚠️  Mesaj kutusu bulunamadı - JavaScript deneniyor")
                
                # JavaScript ile mesaj gönder
                js_script = f'''
                var message = `{message}`;
                var inputBox = document.querySelector('[contenteditable="true"][data-tab="10"]') || 
                               document.querySelector('[contenteditable="true"][role="textbox"]') ||
                               document.querySelector('div[contenteditable="true"]');
                
                if (inputBox) {{
                    inputBox.focus();
                    
                    // Mesajı yaz
                    var lines = message.split('\\n');
                    for (var i = 0; i < lines.length; i++) {{
                        document.execCommand('insertText', false, lines[i]);
                        if (i < lines.length - 1) {{
                            document.execCommand('insertLineBreak');
                        }}
                    }}
                    
                    return true;
                }} else {{
                    return false;
                }}
                '''
                
                try:
                    result = self.driver.execute_script(js_script)
                    if result:
                        print("DEBUG MESSAGE: ✓ JavaScript ile mesaj yazıldı")
                        time.sleep(0.5)
                        
                        # Enter'a bas
                        body = self.driver.find_element(By.TAG_NAME, 'body')
                        body.send_keys(Keys.ENTER)
                        time.sleep(1)
                        
                        print(f"✓ Mesaj gönderildi (JS): '{message}'")
                        return True
                    else:
                        print("⚠️  JavaScript ile de mesaj kutusu bulunamadı")
                        return False
                except Exception as e:
                    print(f"⚠️  JavaScript hatası: {e}")
                    return False
            
            # Selenium ile mesaj gönder
            try:
                # Kutucuğa tıkla ve fokuslan
                compose.click()
                time.sleep(0.5)
                
                # Mevcut içeriği temizle
                compose.clear()
                time.sleep(0.3)
                
                # Mesajı yaz
                lines = message.split('\n')
                for i, line in enumerate(lines):
                    compose.send_keys(line)
                    if i < len(lines) - 1:  # Son satır değilse
                        compose.send_keys(Keys.SHIFT, Keys.ENTER)
                    time.sleep(0.1)
                
                # Gönder
                time.sleep(0.5)
                compose.send_keys(Keys.ENTER)
                time.sleep(1)
                
                print(f"✓ Mesaj gönderildi (Selenium): '{message}'")
                return True
                
            except Exception as e:
                print(f"⚠️  Selenium mesaj gönderme hatası: {e}")
                
                # Son çare: ENTER tuşu
                try:
                    body = self.driver.find_element(By.TAG_NAME, 'body')
                    body.send_keys(Keys.ENTER)
                    print("✓ Mesaj gönderildi (fallback)")
                    return True
                except:
                    return False
            
        except Exception as e:
            print(f"⚠️  Mesaj gönderilemedi: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def send_to_contact(self, contact):
        """Bir kişiye PDF gönder"""
        name = contact['name']
        phone = contact['phone']
        
        print(f"\n{'='*50}")
        print(f"👤 {name} ({phone})")
        print(f"{'='*50}")
        
        try:
            # Sohbeti aç
            if not self.open_chat(phone):
                raise Exception("Sohbet açılamadı")
            
            # PDF'yi ekle
            if not self.attach_pdf():
                raise Exception("PDF eklenemedi")
            
            time.sleep(1)
            
            # PDF'yi gönder
            if not self.send_pdf():
                raise Exception("PDF gönderilemedi")
            
            # PDF gönderildikten sonra bekle
            time.sleep(2)
            
            # Metin mesajı gönder (PDF'den sonra)
            if self.MESSAGE:
                print(f"\nDEBUG: Metin mesajı gönderiliyor...")
                self.send_text_message(name)
                time.sleep(1)
            
            self.sent_count += 1
            print(f"✅ Başarılı! (Toplam: {self.sent_count})")
            
            return True
            
        except Exception as e:
            print(f"❌ Hata: {e}")
            self.failed_contacts.append(contact)
            return False
    
    def run(self):
        """Ana çalıştırma fonksiyonu"""
        try:
            self.init_driver()
            contacts = self.load_contacts()
            
            if len(contacts) > self.DAILY_LIMIT:
                print(f"⚠️  Günlük limit ({self.DAILY_LIMIT}) aşıldı, ilk {self.DAILY_LIMIT} kişi işlenecek")
                contacts = contacts[:self.DAILY_LIMIT]
            
            print(f"\n{'='*50}")
            print(f"🚀 Gönderim başlıyor...")
            print(f"{'='*50}\n")
            
            start_time = datetime.now()
            
            for i, contact in enumerate(contacts, 1):
                print(f"\n[{i}/{len(contacts)}]")
                self.send_to_contact(contact)
                
                if i < len(contacts):
                    print(f"⏳ {self.INTERVAL_SECONDS}s bekleniyor...")
                    time.sleep(self.INTERVAL_SECONDS)
            
            # Özet
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"\n{'='*50}")
            print(f"📊 ÖZET")
            print(f"{'='*50}")
            print(f"✅ Başarılı: {self.sent_count}/{len(contacts)}")
            print(f"❌ Başarısız: {len(self.failed_contacts)}")
            print(f"⏱️  Süre: {elapsed:.1f}s")
            
            if self.failed_contacts:
                print(f"\n❌ Başarısız kişiler:")
                for c in self.failed_contacts:
                    print(f"  - {c['name']} ({c['phone']})")
            
        except KeyboardInterrupt:
            print("\n\n⚠️  İşlem kullanıcı tarafından durduruldu")
        except Exception as e:
            print(f"\n\n❌ Fatal hata: {e}")
        finally:
            if self.driver:
                print("\n🔴 Tarayıcı kapatılıyor...")
                self.driver.quit()

def main():
    parser = argparse.ArgumentParser(description='WhatsApp Web PDF Gönderim Otomasyonu')
    parser.add_argument('--contacts', default='contacts.csv', help='Kişiler CSV dosyası')
    parser.add_argument('--pdf', help='PDF dosya yolu (.env dosyasındaki PDF_PATH yerine)')
    parser.add_argument('--test', action='store_true', help='Test modu (sadece ilk kişi)')
    parser.add_argument('--debug', action='store_true', help='Debug modu (daha fazla log)')
    args = parser.parse_args()
    
    # PDF yolunu belirle
    pdf_path = args.pdf or os.getenv('PDF_PATH', '~/Desktop/brosur.pdf')
    
    print("""
╔══════════════════════════════════════════════════════════╗
║   WhatsApp Web PDF Gönderim Otomasyonu - macOS           ║
║   Geliştirici: Yusufege EREN                             ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    if args.test:
        print("⚠️  TEST MODU - Sadece ilk kişiye gönderim yapılacak\n")
    
    try:
        sender = WhatsAppSender(pdf_path, args.contacts)
        
        # Test modunda tek kişi
        if args.test:
            original_limit = sender.DAILY_LIMIT
            sender.DAILY_LIMIT = 1
        
        sender.run()
    except FileNotFoundError as e:
        print(f"❌ Hata: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Başlatma hatası: {e}")
        import traceback
        if args.debug:
            traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()