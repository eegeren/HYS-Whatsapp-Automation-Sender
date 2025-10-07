#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhatsApp Web PDF Gönderim Otomasyonu - Windows
Kişilere otomatik olarak PDF dosyası gönderir
"""

import os
import sys
import time
import csv
import argparse
import pyautogui
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

# PyAutoGUI ayarları
pyautogui.PAUSE = 0.5
pyautogui.FAILSAFE = True

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
        self.WIN_DIALOG_FALLBACK = os.getenv('WIN_DIALOG_FALLBACK', 'true').lower() == 'true'
        self.WAIT_SECS = float(os.getenv('WAIT_SECS', '0.1'))
        self.USE_PYAUTOGUI = os.getenv('USE_PYAUTOGUI', 'true').lower() == 'true'
        
        # PDF kontrolü
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF dosyası bulunamadı: {self.pdf_path}")
        
        print(f"📄 PDF: {self.pdf_path}")
        print(f"⚙️  Ayarlar: interval={self.INTERVAL_SECONDS}s, limit={self.DAILY_LIMIT}, retries={self.ATTACH_RETRIES}/{self.SEND_RETRIES}")
        
    def init_driver(self):
        """Chrome sürücüsünü başlat"""
        print("🌐 Chrome başlatılıyor...")
        options = webdriver.ChromeOptions()
        
        # Windows için user data dizini
        user_data_dir = os.path.join(os.environ['LOCALAPPDATA'], 'WhatsAppWebSession')
        os.makedirs(user_data_dir, exist_ok=True)
        
        options.add_argument(f'--user-data-dir={user_data_dir}')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        options.page_load_strategy = 'eager'
        
        # Windows'ta bildirim izni
        prefs = {
            "profile.default_content_setting_values.notifications": 1
        }
        options.add_experimental_option("prefs", prefs)
        
        try:
            self.driver = webdriver.Chrome(options=options)
        except Exception as e:
            print(f"❌ Chrome başlatılamadı: {e}")
            print("💡 ChromeDriver'ı yüklediniz mi?")
            print("   İndirme: https://chromedriver.chromium.org/")
            sys.exit(1)
        
        self.driver.get('https://web.whatsapp.com')
        
        print("📱 QR kod ile giriş yapın...")
        self.wait_for_login()
        
    def wait_for_login(self):
        """WhatsApp'a giriş yapılmasını bekle"""
        print("⏳ WhatsApp yükleniyor...")
        time.sleep(3)
        
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
                pass
            
            time.sleep(2)
        
        print("❌ Giriş zaman aşımı")
        print("💡 Manuel olarak giriş yapın ve devam etmek için ENTER'a basın...")
        input()
        return True
            
    def load_contacts(self):
        """Kişileri CSV'den yükle"""
        contacts = []
        try:
            with open(self.contacts_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('name', '').strip()
                    phone = row.get('phone', '').strip().replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                    
                    # Türkiye numarası kontrolü
                    if phone.startswith('0'):
                        phone = '90' + phone[1:]
                    
                    if name and phone:
                        contacts.append({'name': name, 'phone': phone})
            print(f"📋 {len(contacts)} kişi yüklendi")
        except FileNotFoundError:
            print(f"❌ Hata: {self.contacts_file} dosyası bulunamadı!")
            print("💡 contacts.csv dosyası oluşturun:")
            print("   name,phone")
            print("   Ahmet Yılmaz,905551234567")
            sys.exit(1)
        except Exception as e:
            print(f"❌ CSV okuma hatası: {e}")
            sys.exit(1)
        
        return contacts
    
    def open_chat(self, phone):
        """Kişi sohbetini aç - Windows için optimize edilmiş"""
        # Telefon numarasını temizle
        phone = phone.strip().replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        # Türkiye numarası kontrolü
        if phone.startswith('0'):
            phone = '90' + phone[1:]
        
        if not phone.startswith('90'):
            print(f"⚠️  Uyarı: Numara Türkiye kodu (90) ile başlamıyor: {phone}")
        
        if len(phone) < 12:
            print(f"⚠️  Uyarı: Numara çok kısa: {phone}")
            return False
        
        url = f"https://web.whatsapp.com/send?phone={phone}"
        print(f"DEBUG: Açılıyor: {url}")
        self.driver.get(url)
        
        # Sayfa yüklenmesini bekle
        time.sleep(4)
        
        # GEÇERSİZ NUMARA KONTROLÜ
        invalid_indicators = [
            ('[data-testid="invalid-phone"]', 'selector'),
            ('div[data-animate-modal-popup="true"]', 'selector'),
            ('[role="dialog"]', 'selector'),
            ('Telefon numarası', 'text'),
            ('Phone number', 'text'),
            ('geçersiz', 'text'),
            ('invalid', 'text'),
            ('shared via url is invalid', 'text')
        ]
        
        print("DEBUG: Geçersiz numara kontrolü...")
        for indicator, check_type in invalid_indicators:
            try:
                if check_type == 'selector':
                    elems = self.driver.find_elements(By.CSS_SELECTOR, indicator)
                    for elem in elems:
                        if elem.is_displayed():
                            print(f"❌ GEÇERSİZ NUMARA: {phone}")
                            
                            # OK butonunu kapat
                            try:
                                ok_btns = self.driver.find_elements(By.XPATH, "//div[@role='button' and contains(text(), 'OK')]")
                                if ok_btns:
                                    ok_btns[0].click()
                            except:
                                pass
                            
                            return False
                
                elif check_type == 'text':
                    body_text = self.driver.find_element(By.TAG_NAME, 'body').text.lower()
                    if indicator.lower() in body_text:
                        print(f"❌ GEÇERSİZ NUMARA: {phone}")
                        return False
            except:
                pass
        
        # SOHBET KUTUSU KONTROLÜ
        chat_selectors = [
            '[data-testid="conversation-compose-box-input"]',
            '[contenteditable="true"][data-tab="10"]',
            'div[contenteditable="true"][role="textbox"]',
            'footer div[contenteditable="true"]',
            '[data-testid="compose-box-input"]'
        ]
        
        max_wait = 20
        print(f"DEBUG: Sohbet kutusu bekleniyor (max {max_wait}s)...")
        
        for i in range(int(max_wait / self.WAIT_SECS)):
            for selector in chat_selectors:
                try:
                    elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if elem.is_displayed():
                        print(f"DEBUG: ✓ Sohbet kutusu bulundu")
                        time.sleep(1)
                        return True
                except:
                    pass
            
            if i > 0 and i % int(5 / self.WAIT_SECS) == 0:
                elapsed = i * self.WAIT_SECS
                print(f"DEBUG: Hala bekleniyor... ({elapsed:.1f}s)")
            
            time.sleep(self.WAIT_SECS)
        
        print("⚠️  Sohbet kutusu bulunamadı")
        
        # Screenshot al
        try:
            screenshot_path = f"debug_{phone}_{int(time.time())}.png"
            self.driver.save_screenshot(screenshot_path)
            print(f"DEBUG: Screenshot: {screenshot_path}")
        except:
            pass
        
        print("\n" + "="*50)
        print("💡 MANUEL KONTROL")
        print("="*50)
        print(f"Numara: {phone}")
        print("\nSohbet AÇIKSA: 'y' + ENTER")
        print("Numara GEÇERSİZSE: 'n' + ENTER")
        print("="*50)
        
        response = input(">> ").strip().lower()
        return response == 'y'
    
    def find_file_input(self):
        """PDF input elementini bul"""
        if self.cached_file_input and not self.FORCE_DIALOG_MODE:
            try:
                self.cached_file_input.is_enabled()
                print("DEBUG: Cache'den input kullanılıyor")
                return self.cached_file_input
            except:
                self.cached_file_input = None
        
        print("DEBUG: File input aranıyor...")
        selectors = [
            'input[type="file"][accept*="application/pdf"]',
            'input[type="file"][accept*="*"]',
            'input[type="file"]'
        ]
        
        for selector in selectors:
            try:
                inputs = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for inp in inputs:
                    self.cached_file_input = inp
                    print(f"DEBUG: ✓ Input bulundu")
                    return inp
            except:
                pass
        
        return None
    
    def use_windows_dialog(self):
        """Windows dosya seçim diyaloğunu PyAutoGUI ile kontrol et"""
        print("DEBUG: Windows dialog modu aktif")
        
        try:
            # Dosya seçim penceresinin açılmasını bekle
            time.sleep(2)
            
            # PDF yolunu yazabilmek için Ctrl+L (adres çubuğu)
            print("DEBUG: Dosya yolu yazılıyor...")
            pyautogui.hotkey('ctrl', 'l')
            time.sleep(0.5)
            
            # PDF yolunu yaz
            pdf_path_str = str(self.pdf_path)
            pyautogui.write(pdf_path_str, interval=0.05)
            time.sleep(0.5)
            
            # Enter ile aç
            pyautogui.press('enter')
            time.sleep(1)
            
            print("DEBUG: ✓ PDF seçildi")
            return True
            
        except Exception as e:
            print(f"DEBUG: PyAutoGUI hatası: {e}")
            return False
    
    def attach_pdf(self):
        """PDF'yi ekle - Windows için"""
        for attempt in range(self.ATTACH_RETRIES):
            print(f"DEBUG: PDF ekleme {attempt + 1}/{self.ATTACH_RETRIES}")
            
            time.sleep(1)
            
            # Ekleme butonunu bul
            attach_selectors = [
                'div[aria-label="Ekle"]',
                'div[aria-label="Attach"]',
                'div[title="Ekle"]',
                'button[aria-label="Ekle"]',
                '[data-testid="clip"]',
                '[data-icon="clip"]',
                'span[data-icon="clip"]',
                'div[role="button"] span[data-icon="plus"]'
            ]
            
            clicked = False
            for selector in attach_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    
                    if elements:
                        for elem in elements:
                            try:
                                if elem.is_displayed():
                                    elem.click()
                                    print(f"DEBUG: ✓ Ekle butonu tıklandı")
                                    time.sleep(1.5)
                                    clicked = True
                                    break
                            except:
                                continue
                    
                    if clicked:
                        break
                except:
                    continue
            
            # JavaScript fallback
            if not clicked:
                try:
                    print("DEBUG: JavaScript ile deneniyor...")
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
                        print("DEBUG: ✓ JavaScript ile tıklandı")
                        time.sleep(1.5)
                        clicked = True
                except Exception as e:
                    print(f"DEBUG: JS hatası: {e}")
                
                if not clicked:
                    print("💡 Manuel olarak + (Ekle) butonuna tıklayın ve ENTER'a basın...")
                    input()
                    clicked = True
            
            # Belge seçeneğine tıkla
            if clicked:
                time.sleep(1)
                doc_selectors = [
                    'li[aria-label="Belge"]',
                    'li[aria-label="Document"]',
                    'button[aria-label="Belge"]',
                    '[data-testid="attach-document"]'
                ]
                
                doc_clicked = False
                for selector in doc_selectors:
                    try:
                        doc_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        
                        if doc_elements:
                            for doc_elem in doc_elements:
                                if doc_elem.tag_name != 'input':
                                    try:
                                        doc_elem.click()
                                        print(f"DEBUG: ✓ Belge tıklandı")
                                        time.sleep(1)
                                        doc_clicked = True
                                        break
                                    except:
                                        continue
                        
                        if doc_clicked:
                            break
                    except:
                        continue
                
                # JavaScript ile belge seç
                if not doc_clicked:
                    try:
                        js_script = """
                        const items = document.querySelectorAll('li[role="button"], button');
                        for (let item of items) {
                            const label = item.getAttribute('aria-label') || item.textContent || '';
                            if (label.toLowerCase().includes('belge') || 
                                label.toLowerCase().includes('document')) {
                                item.click();
                                return true;
                            }
                        }
                        return false;
                        """
                        result = self.driver.execute_script(js_script)
                        if result:
                            print("DEBUG: ✓ Belge JS ile tıklandı")
                            time.sleep(1)
                    except:
                        pass
            
            # File input ile gönder (öncelikli)
            if not self.FORCE_DIALOG_MODE:
                file_input = self.find_file_input()
                if file_input:
                    try:
                        file_input.send_keys(str(self.pdf_path))
                        print("DEBUG: ✓ PDF yüklendi (send_keys)")
                        time.sleep(2)
                        return True
                    except Exception as e:
                        print(f"DEBUG: send_keys hatası: {e}")
            
            # PyAutoGUI fallback (Windows)
            if self.WIN_DIALOG_FALLBACK or self.FORCE_DIALOG_MODE:
                if self.USE_PYAUTOGUI:
                    print("DEBUG: PyAutoGUI deneniyor...")
                    if self.use_windows_dialog():
                        time.sleep(2)
                        return True
            
            if attempt < self.ATTACH_RETRIES - 1:
                print("DEBUG: Yeniden deneniyor...")
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
            '[data-testid="send-button"]'
        ]
        
        while time.time() - start < self.PREVIEW_TIMEOUT:
            for selector in preview_selectors:
                try:
                    preview = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if preview.is_displayed():
                        print(f"DEBUG: ✓ Önizleme bulundu")
                        return True
                except:
                    pass
            time.sleep(self.WAIT_SECS)
        
        print("DEBUG: Önizleme bulunamadı")
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
                    print(f"DEBUG: ✓ Gönder tıklandı")
                    return True
            except:
                pass
        
        return False
    
    def send_pdf(self):
        """PDF'yi gönder"""
        initial_count = self.count_sent_messages()
        print(f"DEBUG: Başlangıç mesaj sayısı: {initial_count}")
        
        for attempt in range(self.SEND_RETRIES):
            print(f"DEBUG: Gönderim {attempt + 1}/{self.SEND_RETRIES}")
            
            self.wait_for_preview()
            time.sleep(1)
            
            send_clicked = self.click_send_button()
            
            if send_clicked:
                print("DEBUG: Gönder butonu tıklandı")
                time.sleep(3)
            else:
                print("DEBUG: ENTER deneniyor")
                try:
                    body = self.driver.find_element(By.TAG_NAME, 'body')
                    body.send_keys(Keys.ENTER)
                    time.sleep(0.5)
                    body.send_keys(Keys.ENTER)
                    time.sleep(3)
                except:
                    pass
            
            # Gönderim kontrolü
            for check in range(5):
                time.sleep(1)
                new_count = self.count_sent_messages()
                print(f"DEBUG: Kontrol {check + 1}/5 - Önceki: {initial_count}, Şimdi: {new_count}")
                
                if new_count > initial_count:
                    print("✓ PDF gönderildi")
                    return True
            
            if attempt < self.SEND_RETRIES - 1:
                print("DEBUG: Yeniden deneniyor...")
                time.sleep(2)
        
        print("⚠️  Gönderim otomatik algılanamadı")
        print("💡 PDF gönderildiyse 'y' + ENTER:")
        response = input().strip().lower()
        return response == 'y'
    
    def count_sent_messages(self):
        """Gönderilen mesaj sayısını say"""
        try:
            selectors = [
                '[data-testid="msg-container"].message-out',
                'div.message-out'
            ]
            
            for selector in selectors:
                try:
                    msgs = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if msgs:
                        return len(msgs)
                except:
                    continue
            
            return 0
        except:
            return 0
    
    def send_text_message(self, name):
        """Metin mesajı gönder"""
        if not self.MESSAGE:
            return True
        
        try:
            message = self.MESSAGE.replace('{name}', name)
            print(f"DEBUG: Mesaj: '{message}'")
            
            time.sleep(1)
            
            compose_selectors = [
                '[data-testid="conversation-compose-box-input"]',
                '[contenteditable="true"][data-tab="10"]',
                'div[contenteditable="true"][role="textbox"]',
                'footer div[contenteditable="true"]'
            ]
            
            compose = None
            for selector in compose_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    
                    for elem in elements:
                        if elem.is_displayed():
                            compose = elem
                            break
                    
                    if compose:
                        break
                except:
                    continue
            
            if not compose:
                # JavaScript ile mesaj gönder
                js_script = f'''
                var message = `{message}`;
                var inputBox = document.querySelector('[contenteditable="true"][data-tab="10"]') || 
                               document.querySelector('[contenteditable="true"][role="textbox"]');
                
                if (inputBox) {{
                    inputBox.focus();
                    document.execCommand('insertText', false, message);
                    return true;
                }} else {{
                    return false;
                }}
                '''
                
                try:
                    result = self.driver.execute_script(js_script)
                    if result:
                        time.sleep(0.5)
                        body = self.driver.find_element(By.TAG_NAME, 'body')
                        body.send_keys(Keys.ENTER)
                        time.sleep(1)
                        print(f"✓ Mesaj gönderildi (JS)")
                        return True
                except:
                    return False
            
            # Selenium ile mesaj gönder
            try:
                compose.click()
                time.sleep(0.5)
                
                lines = message.split('\n')
                for i, line in enumerate(lines):
                    compose.send_keys(line)
                    if i < len(lines) - 1:
                        compose.send_keys(Keys.SHIFT, Keys.ENTER)
                    time.sleep(0.1)
                
                time.sleep(0.5)
                compose.send_keys(Keys.ENTER)
                time.sleep(1)
                
                print(f"✓ Mesaj gönderildi")
                return True
                
            except Exception as e:
                print(f"⚠️  Mesaj hatası: {e}")
                return False
            
        except Exception as e:
            print(f"⚠️  Mesaj gönderilemedi: {e}")
            return False
    
    def send_to_contact(self, contact):
        """Bir kişiye PDF gönder"""
        name = contact['name']
        phone = contact['phone']
        
        print(f"\n{'='*50}")
        print(f"👤 {name} ({phone})")
        print(f"{'='*50}")
        
        try:
            if not self.open_chat(phone):
                raise Exception("Sohbet açılamadı")
            
            if not self.attach_pdf():
                raise Exception("PDF eklenemedi")
            
            time.sleep(1)
            
            if not self.send_pdf():
                raise Exception("PDF gönderilemedi")
            
            time.sleep(2)
            
            if self.MESSAGE:
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
                print(f"⚠️  Limit aşıldı, ilk {self.DAILY_LIMIT} kişi işlenecek")
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
            print("\n\n⚠️  İşlem durduruldu")
        except Exception as e:
            print(f"\n\n❌ Hata: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.driver:
                print("\n🔴 Tarayıcı kapatılıyor...")
                self.driver.quit()

def main():
    parser = argparse.ArgumentParser(description='WhatsApp Web PDF Gönderim Otomasyonu - Windows')
    parser.add_argument('--contacts', default='contacts.csv', help='Kişiler CSV dosyası')
    parser.add_argument('--pdf', help='PDF dosya yolu (.env dosyasındaki PDF_PATH yerine)')
    parser.add_argument('--test', action='store_true', help='Test modu (sadece ilk kişi)')
    parser.add_argument('--debug', action='store_true', help='Debug modu (daha fazla log)')
    args = parser.parse_args()
    
    pdf_path = args.pdf or os.getenv('PDF_PATH', 'C:\\Users\\Public\\Documents\\brosur.pdf')
    
    print("""
╔══════════════════════════════════════════════════════════╗
║   WhatsApp Web PDF Gönderim Otomasyonu - Windows         ║
║   Geliştirici: Yusufege EREN                             ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    if args.test:
        print("⚠️  TEST MODU - Sadece ilk kişiye gönderim yapılacak\n")
    
    try:
        sender = WhatsAppSender(pdf_path, args.contacts)
        
        if args.test:
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