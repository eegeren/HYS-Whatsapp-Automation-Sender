#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WhatsApp Web PDF Gönderim Otomasyonu - Windows
Zamanlanmış gönderim: 09:00-20:00 arası, 15 dakika arayla, günde 50 kişi
"""

import os
import sys
import time
import csv
import json
import argparse
import pyautogui
from pathlib import Path
from datetime import datetime, timedelta
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

class ProgressTracker:
    """Gönderim ilerlemesini takip et"""
    def __init__(self, progress_file='progress.json'):
        self.progress_file = progress_file
        self.data = self.load()
    
    def load(self):
        """İlerlemeyi yükle"""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        
        return {
            'last_date': None,
            'sent_today': 0,
            'total_sent': 0,
            'last_index': -1,
            'failed_contacts': []
        }
    
    def save(self):
        """İlerlemeyi kaydet"""
        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
    
    def reset_daily(self):
        """Günlük sayacı sıfırla"""
        today = datetime.now().strftime('%Y-%m-%d')
        if self.data['last_date'] != today:
            print(f"📅 Yeni gün başlıyor: {today}")
            self.data['last_date'] = today
            self.data['sent_today'] = 0
            self.save()
    
    def can_send_today(self, daily_limit):
        """Bugün daha gönderim yapılabilir mi?"""
        self.reset_daily()
        return self.data['sent_today'] < daily_limit
    
    def mark_sent(self, index):
        """Gönderim başarılı olarak işaretle"""
        self.data['sent_today'] += 1
        self.data['total_sent'] += 1
        self.data['last_index'] = index
        self.save()
    
    def mark_failed(self, contact):
        """Başarısız gönderimi kaydet"""
        self.data['failed_contacts'].append({
            'name': contact['name'],
            'phone': contact['phone'],
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        self.save()

class WhatsAppSender:
    def __init__(self, pdf_path, contacts_file):
        self.pdf_path = Path(pdf_path).expanduser().resolve()
        self.contacts_file = contacts_file
        self.driver = None
        self.cached_file_input = None
        self.progress = ProgressTracker()
        
        # Ayarlar
        self.MESSAGE = os.getenv('MESSAGE', '')
        self.DAILY_LIMIT = int(os.getenv('DAILY_LIMIT', '50'))
        self.INTERVAL_MINUTES = int(os.getenv('INTERVAL_MINUTES', '15'))
        self.WORK_START_HOUR = int(os.getenv('WORK_START_HOUR', '9'))
        self.WORK_END_HOUR = int(os.getenv('WORK_END_HOUR', '20'))
        self.ATTACH_RETRIES = int(os.getenv('ATTACH_RETRIES', '3'))
        self.SEND_RETRIES = int(os.getenv('SEND_RETRIES', '3'))
        self.PREVIEW_TIMEOUT = float(os.getenv('PREVIEW_TIMEOUT', '10'))
        self.FORCE_DIALOG_MODE = os.getenv('FORCE_DIALOG_MODE', 'false').lower() == 'true'
        self.WIN_DIALOG_FALLBACK = os.getenv('WIN_DIALOG_FALLBACK', 'true').lower() == 'true'
        self.WAIT_SECS = float(os.getenv('WAIT_SECS', '0.1'))
        self.USE_PYAUTOGUI = os.getenv('USE_PYAUTOGUI', 'true').lower() == 'true'
        self.AUTO_RESTART = os.getenv('AUTO_RESTART', 'true').lower() == 'true'
        
        # PDF kontrolü
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF dosyası bulunamadı: {self.pdf_path}")
        
        print(f"📄 PDF: {self.pdf_path}")
        print(f"⚙️  Ayarlar:")
        print(f"   - Günlük limit: {self.DAILY_LIMIT} kişi")
        print(f"   - Gönderim aralığı: {self.INTERVAL_MINUTES} dakika")
        print(f"   - Çalışma saatleri: {self.WORK_START_HOUR}:00 - {self.WORK_END_HOUR}:00")
        print(f"   - Bugün gönderilen: {self.progress.data['sent_today']}")
        print(f"   - Toplam gönderilen: {self.progress.data['total_sent']}")
        
    def is_working_hours(self):
        """Çalışma saatleri içinde mi kontrol et"""
        now = datetime.now()
        current_hour = now.hour
        
        if current_hour < self.WORK_START_HOUR or current_hour >= self.WORK_END_HOUR:
            return False
        return True
    
    def wait_for_working_hours(self):
        """Çalışma saatlerini bekle"""
        while not self.is_working_hours():
            now = datetime.now()
            current_hour = now.hour
            
            if current_hour < self.WORK_START_HOUR:
                # Sabah saatlerini bekle
                start_time = now.replace(hour=self.WORK_START_HOUR, minute=0, second=0)
                wait_seconds = (start_time - now).total_seconds()
                print(f"\n⏰ Çalışma saatleri dışında!")
                print(f"   Beklenen başlama: {start_time.strftime('%H:%M:%S')}")
                print(f"   Kalan süre: {wait_seconds/3600:.1f} saat")
            else:
                # Yarın sabahı bekle
                tomorrow = now + timedelta(days=1)
                start_time = tomorrow.replace(hour=self.WORK_START_HOUR, minute=0, second=0)
                wait_seconds = (start_time - now).total_seconds()
                print(f"\n🌙 Mesai bitti!")
                print(f"   Yarın başlama: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Kalan süre: {wait_seconds/3600:.1f} saat")
            
            # Her 10 dakikada bir durum göster
            sleep_interval = min(600, wait_seconds)  # 10 dakika veya kalan süre
            time.sleep(sleep_interval)
    
    def calculate_next_send_time(self):
        """Sonraki gönderim zamanını hesapla"""
        return datetime.now() + timedelta(minutes=self.INTERVAL_MINUTES)
    
    def wait_until(self, target_time):
        """Belirli bir zamana kadar bekle"""
        while datetime.now() < target_time:
            remaining = (target_time - datetime.now()).total_seconds()
            
            if remaining <= 0:
                break
            
            # Her dakika durum göster
            if remaining > 60:
                mins = int(remaining / 60)
                print(f"⏳ Sonraki gönderime {mins} dakika {int(remaining % 60)} saniye...", end='\r')
                time.sleep(min(60, remaining))
            else:
                print(f"⏳ Sonraki gönderime {int(remaining)} saniye...     ", end='\r')
                time.sleep(min(1, remaining))
        
        print()  # Yeni satır
        
    def init_driver(self):
        """Chrome sürücüsünü başlat"""
        print("🌐 Chrome başlatılıyor...")
        options = webdriver.ChromeOptions()
        
        user_data_dir = os.path.join(os.environ['LOCALAPPDATA'], 'WhatsAppWebSession')
        os.makedirs(user_data_dir, exist_ok=True)
        
        options.add_argument(f'--user-data-dir={user_data_dir}')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        options.page_load_strategy = 'eager'
        
        prefs = {
            "profile.default_content_setting_values.notifications": 1
        }
        options.add_experimental_option("prefs", prefs)
        
        try:
            self.driver = webdriver.Chrome(options=options)
        except Exception as e:
            print(f"❌ Chrome başlatılamadı: {e}")
            print("💡 ChromeDriver yükleyin: pip install webdriver-manager")
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
                qr = self.driver.find_elements(By.CSS_SELECTOR, 'canvas[aria-label*="QR"]')
                if qr and qr[0].is_displayed():
                    if not login_detected:
                        print("📱 QR kodu telefonunuzla tarayın...")
                        login_detected = True
                
                chat_list = self.driver.find_elements(By.CSS_SELECTOR, '[data-testid="chat-list"]')
                if chat_list:
                    print("✓ WhatsApp'a giriş yapıldı")
                    time.sleep(3)
                    return True
                
                side_panel = self.driver.find_elements(By.ID, 'side')
                pane_side = self.driver.find_elements(By.CSS_SELECTOR, '[data-testid="chatlist-header"]')
                
                if side_panel or pane_side:
                    print("✓ WhatsApp'a giriş yapıldı")
                    time.sleep(3)
                    return True
                    
            except:
                pass
            
            time.sleep(2)
        
        print("❌ Giriş zaman aşımı")
        print("💡 Manuel giriş yapın ve ENTER'a basın...")
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
                    
                    if phone.startswith('0'):
                        phone = '90' + phone[1:]
                    
                    if name and phone:
                        contacts.append({'name': name, 'phone': phone})
            print(f"📋 {len(contacts)} kişi yüklendi")
        except FileNotFoundError:
            print(f"❌ {self.contacts_file} bulunamadı!")
            sys.exit(1)
        
        return contacts
    
    def get_pending_contacts(self, all_contacts):
        """Gönderilmemiş kişileri al"""
        last_index = self.progress.data['last_index']
        pending = all_contacts[last_index + 1:]
        
        if pending:
            print(f"📊 Kalan kişi sayısı: {len(pending)}")
        else:
            print(f"✅ Tüm kişilere gönderim tamamlandı!")
            print(f"💡 Yeni kişi eklemek için contacts.csv dosyasını güncelleyin")
            print(f"💡 Veya ilerlemeyi sıfırlamak için progress.json dosyasını silin")
        
        return pending
    
    def open_chat(self, phone):
        """Kişi sohbetini aç"""
        phone = phone.strip().replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        
        if phone.startswith('0'):
            phone = '90' + phone[1:]
        
        url = f"https://web.whatsapp.com/send?phone={phone}"
        print(f"DEBUG: Açılıyor: {url}")
        self.driver.get(url)
        
        time.sleep(4)
        
        # Geçersiz numara kontrolü
        try:
            body_text = self.driver.find_element(By.TAG_NAME, 'body').text.lower()
            if 'invalid' in body_text or 'geçersiz' in body_text:
                print(f"❌ GEÇERSİZ NUMARA: {phone}")
                return False
        except:
            pass
        
        # Sohbet kutusu kontrolü
        chat_selectors = [
            '[data-testid="conversation-compose-box-input"]',
            '[contenteditable="true"][data-tab="10"]',
            'div[contenteditable="true"][role="textbox"]'
        ]
        
        max_wait = 15
        for i in range(int(max_wait / self.WAIT_SECS)):
            for selector in chat_selectors:
                try:
                    elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if elem.is_displayed():
                        print(f"DEBUG: ✓ Sohbet açıldı")
                        time.sleep(1)
                        return True
                except:
                    pass
            time.sleep(self.WAIT_SECS)
        
        print("⚠️  Sohbet açılamadı")
        return False
    
    def find_file_input(self):
        """PDF input elementini bul"""
        selectors = [
            'input[type="file"][accept*="application/pdf"]',
            'input[type="file"]'
        ]
        
        for selector in selectors:
            try:
                inputs = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for inp in inputs:
                    return inp
            except:
                pass
        
        return None
    
    def use_windows_dialog(self):
        """Windows dosya diyaloğunu PyAutoGUI ile kontrol et"""
        try:
            time.sleep(2)
            pyautogui.hotkey('ctrl', 'l')
            time.sleep(0.5)
            pyautogui.write(str(self.pdf_path), interval=0.05)
            time.sleep(0.5)
            pyautogui.press('enter')
            time.sleep(1)
            return True
        except:
            return False
    
    def attach_pdf(self):
        """PDF'yi ekle"""
        for attempt in range(self.ATTACH_RETRIES):
            time.sleep(1)
            
            # Ekle butonunu bul
            attach_selectors = [
                'div[aria-label="Ekle"]',
                'div[aria-label="Attach"]',
                '[data-testid="clip"]',
                'span[data-icon="clip"]'
            ]
            
            clicked = False
            for selector in attach_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements and elements[0].is_displayed():
                        elements[0].click()
                        print(f"DEBUG: ✓ Ekle tıklandı")
                        time.sleep(1.5)
                        clicked = True
                        break
                except:
                    pass
            
            if clicked:
                time.sleep(1)
                # Belge seçeneği
                doc_selectors = [
                    'li[aria-label="Belge"]',
                    'li[aria-label="Document"]'
                ]
                
                for selector in doc_selectors:
                    try:
                        doc = self.driver.find_element(By.CSS_SELECTOR, selector)
                        doc.click()
                        print(f"DEBUG: ✓ Belge seçildi")
                        time.sleep(1)
                        break
                    except:
                        pass
            
            # File input ile gönder
            if not self.FORCE_DIALOG_MODE:
                file_input = self.find_file_input()
                if file_input:
                    try:
                        file_input.send_keys(str(self.pdf_path))
                        print("DEBUG: ✓ PDF yüklendi")
                        time.sleep(2)
                        return True
                    except:
                        pass
            
            # PyAutoGUI fallback
            if self.USE_PYAUTOGUI:
                if self.use_windows_dialog():
                    time.sleep(2)
                    return True
            
            if attempt < self.ATTACH_RETRIES - 1:
                time.sleep(2)
        
        return False
    
    def send_pdf(self):
        """PDF'yi gönder"""
        time.sleep(2)
        
        # Gönder butonunu bul
        send_selectors = [
            '[data-testid="media-preview-send"]',
            '[aria-label*="Gönder"]',
            '[data-icon="send"]'
        ]
        
        for selector in send_selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                if btn.is_displayed():
                    btn.click()
                    print("DEBUG: ✓ Gönder tıklandı")
                    time.sleep(3)
                    return True
            except:
                pass
        
        # ENTER fallback
        try:
            body = self.driver.find_element(By.TAG_NAME, 'body')
            body.send_keys(Keys.ENTER)
            time.sleep(3)
            return True
        except:
            return False
    
    def send_text_message(self, name):
        """Metin mesajı gönder"""
        if not self.MESSAGE:
            return True
        
        try:
            message = self.MESSAGE.replace('{name}', name)
            time.sleep(1)
            
            js_script = f'''
            var message = `{message}`;
            var inputBox = document.querySelector('[contenteditable="true"][data-tab="10"]') || 
                           document.querySelector('[contenteditable="true"][role="textbox"]');
            
            if (inputBox) {{
                inputBox.focus();
                document.execCommand('insertText', false, message);
                return true;
            }}
            return false;
            '''
            
            result = self.driver.execute_script(js_script)
            if result:
                time.sleep(0.5)
                body = self.driver.find_element(By.TAG_NAME, 'body')
                body.send_keys(Keys.ENTER)
                time.sleep(1)
                print(f"✓ Mesaj gönderildi")
                return True
        except:
            pass
        
        return False
    
    def send_to_contact(self, contact, index):
        """Bir kişiye PDF gönder"""
        name = contact['name']
        phone = contact['phone']
        
        print(f"\n{'='*60}")
        print(f"👤 [{index + 1}] {name} ({phone})")
        print(f"   Bugün: {self.progress.data['sent_today'] + 1}/{self.DAILY_LIMIT}")
        print(f"   Toplam: {self.progress.data['total_sent'] + 1}")
        print(f"{'='*60}")
        
        try:
            if not self.open_chat(phone):
                raise Exception("Sohbet açılamadı")
            
            if not self.attach_pdf():
                raise Exception("PDF eklenemedi")
            
            if not self.send_pdf():
                raise Exception("PDF gönderilemedi")
            
            time.sleep(2)
            
            if self.MESSAGE:
                self.send_text_message(name)
            
            self.progress.mark_sent(index)
            print(f"✅ Başarılı!")
            
            return True
            
        except Exception as e:
            print(f"❌ Hata: {e}")
            self.progress.mark_failed(contact)
            return False
    
    def run(self):
        """Ana çalıştırma fonksiyonu - Sürekli döngü"""
        print(f"\n{'='*60}")
        print(f"🚀 ZAMANLI GÖNDERIM BAŞLIYOR")
        print(f"{'='*60}\n")
        
        try:
            self.init_driver()
            all_contacts = self.load_contacts()
            
            while True:
                # Çalışma saatlerini kontrol et
                if not self.is_working_hours():
                    print(f"\n⏰ Mesai dışı - Bekleniyor...")
                    self.wait_for_working_hours()
                
                # Günlük limit kontrolü
                self.progress.reset_daily()
                if not self.progress.can_send_today(self.DAILY_LIMIT):
                    print(f"\n🎯 Günlük limit doldu ({self.DAILY_LIMIT})")
                    print(f"   Yarın devam edilecek...")
                    self.wait_for_working_hours()
                    continue
                
                # Gönderilecek kişileri al
                pending = self.get_pending_contacts(all_contacts)
                if not pending:
                    print(f"\n✅ Tüm kişiler tamamlandı!")
                    break
                
                # Bir sonraki kişiye gönder
                contact = pending[0]
                index = self.progress.data['last_index'] + 1
                
                success = self.send_to_contact(contact, index)
                
                # Sonraki gönderim zamanını hesapla
                if len(pending) > 1:
                    next_time = self.calculate_next_send_time()
                    print(f"\n⏰ Sonraki gönderim: {next_time.strftime('%H:%M:%S')}")
                    self.wait_until(next_time)
                else:
                    print(f"\n✅ Liste tamamlandı!")
                    break
            
        except KeyboardInterrupt:
            print("\n\n⚠️  İşlem durduruldu")
            print(f"📊 Bugün gönderilen: {self.progress.data['sent_today']}")
            print(f"📊 Toplam gönderilen: {self.progress.data['total_sent']}")
        except Exception as e:
            print(f"\n\n❌ Hata: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.driver:
                print("\n🔴 Tarayıcı kapatılıyor...")
                self.driver.quit()

def main():
    parser = argparse.ArgumentParser(description='WhatsApp Zamanlanmış PDF Gönderimi')
    parser.add_argument('--contacts', default='contacts.csv', help='Kişiler CSV')
    parser.add_argument('--pdf', help='PDF dosya yolu')
    parser.add_argument('--reset', action='store_true', help='İlerlemeyi sıfırla')
    args = parser.parse_args()
    
    if args.reset:
        if os.path.exists('progress.json'):
            os.remove('progress.json')
            print("✓ İlerleme sıfırlandı")
        sys.exit(0)
    
    pdf_path = args.pdf or os.getenv('PDF_PATH', 'C:\\Users\\Public\\Documents\\brosur.pdf')
    
    print("""
╔══════════════════════════════════════════════════════════╗
║   WhatsApp Zamanlanmış PDF Gönderimi - Windows          ║
║   09:00-20:00 arası, 15dk aralık, günde 50 kişi        ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    try:
        sender = WhatsAppSender(pdf_path, args.contacts)
        sender.run()
    except Exception as e:
        print(f"❌ Hata: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()