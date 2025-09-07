import sys
import yaml
import random
import requests
import hashlib
import json
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QWidget, QLabel
from PyQt6.QtCore import Qt, QTimer, QUrl, QTime
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

SERVER_URL = "http://192.168.0.25:5000"
CLIENT_ID = "testclient"
CACHE_DIR = Path(__file__).parent / "cache"
MEDIA_DIR = CACHE_DIR / "media"
CONFIG_CACHE_FILE = CACHE_DIR / "config.json"
CONFIG_HASH_FILE = CACHE_DIR / "config_hash.txt"

CACHE_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)

# ------------------ Helpers ------------------
def get_config_from_server():
    try:
        resp = requests.get(f"{SERVER_URL}/config/{CLIENT_ID}", timeout=5)
        resp.raise_for_status()
        config = resp.json()
        print("[DEBUG] Fetched config from server")
        return config
    except Exception as e:
        print(f"[WARNING] Could not fetch config from server: {e}")
        return None

def hash_config(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()

def save_config_cache(config):
    with open(CONFIG_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f)
    with open(CONFIG_HASH_FILE, "w", encoding="utf-8") as f:
        f.write(hash_config(config))

def load_config_cache():
    if CONFIG_CACHE_FILE.exists():
        with open(CONFIG_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def load_config_hash():
    if CONFIG_HASH_FILE.exists():
        with open(CONFIG_HASH_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None

def download_media(url, filename):
    local_path = MEDIA_DIR / filename
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(resp.content)
        print(f"[DEBUG] Downloaded {filename}")
    except Exception as e:
        print(f"[WARNING] Failed to download {filename}: {e}")
    return local_path

def ensure_media_files(config):
    media_map = {}
    # Logo
    logo_url = config.get("logo")
    if logo_url:
        media_map[logo_url] = Path(logo_url).name
        config["logo"] = str(MEDIA_DIR / Path(logo_url).name)
    # Background
    bg_url = config.get("background_image")
    if bg_url:
        media_map[bg_url] = Path(bg_url).name
        config["background_image"] = str(MEDIA_DIR / Path(bg_url).name)
    # Slides
    for slide in config.get("slides", []):
        for side in ["left", "right"]:
            conf = slide.get(side, {})
            if conf.get("type") in ["image", "video"]:
                src_url = conf.get("source")
                if src_url:
                    media_map[src_url] = Path(src_url).name
                    conf["source"] = str(MEDIA_DIR / Path(src_url).name)
    # Download missing files
    for url, fname in media_map.items():
        local_path = MEDIA_DIR / fname
        if not local_path.exists():
            download_media(url, fname)
    return config

# ------------------ Main Window ------------------
class MainWindow(QWidget):
    def __init__(self, slides_config, settings, motd_config):
        super().__init__()
        self.setWindowTitle(settings.get("display_name", ""))
        self.resize(1920, 1080)
        self.win_w, self.win_h = 1920, 1080

        self.slides = slides_config.get("slides", [])
        self.current_slide_index = -1

        # ----------------- Background -----------------
        bg_path = settings.get("background_image")
        if bg_path and Path(bg_path).exists():
            self.bg_label = QLabel(self)
            self.bg_label.setPixmap(QPixmap(bg_path).scaled(self.win_w, self.win_h, Qt.AspectRatioMode.KeepAspectRatioByExpanding))
            self.bg_label.setGeometry(0,0,self.win_w,self.win_h)
            self.bg_label.show()
        else:
            self.bg_label = None

        # ----------------- Logo -----------------
        hide_logo = settings.get("hide_logo", False)
        logo_path = settings.get("logo")
        if logo_path and Path(logo_path).exists() and not hide_logo:
            self.logo_label = QLabel(self)
            self.logo_label.setPixmap(QPixmap(logo_path))
            self.logo_label.setGeometry(10, 10, 200, 100)
            self.logo_label.show()
        else:
            self.logo_label = None

        # ----------------- Clock -----------------
        clock_conf = settings.get("clock") or {}
        clock_enabled = clock_conf.get("enabled", True)
        if clock_enabled:
            self.clock_label = QLabel(self)
            self.clock_label.setFont(QFont(clock_conf.get("font","Arial"), 32))
            self.clock_label.setStyleSheet(f"color:{clock_conf.get('color','#FFFFFF')};")
            self.clock_label.setGeometry(int(0.8*self.win_w), 10, int(0.2*self.win_w), 50)
            self.clock_label.show()
            self.clock_timer = QTimer()
            self.clock_timer.timeout.connect(self.update_clock)
            self.clock_timer.start(1000)
            self.update_clock()
        else:
            self.clock_label = None
            self.clock_timer = None

        # ----------------- Horizontal Scroller -----------------
        self.motd_label = QLabel(self)
        self.motd_label.setFont(QFont(motd_config.get("font","Arial"), motd_config.get("size",24)))
        self.motd_label.setText(motd_config.get("text",""))
        self.motd_label.setStyleSheet(f"color:{motd_config.get('color','#FFFFFF')}; background:transparent;")
        self.motd_label.adjustSize()
        self.ticker_speed = motd_config.get("speed",3)
        self.ticker_x = int(self.win_w * motd_config.get("horizontal_from_percent",5)/100)
        self.ticker_y = int(self.win_h * motd_config.get("height_percent",90)/100)
        self.ticker_width = int(self.win_w * (motd_config.get("horizontal_to_percent",95)/100 - motd_config.get("horizontal_from_percent",5)/100))
        self.motd_label.move(self.ticker_x, self.ticker_y)
        self.motd_timer = QTimer()
        self.motd_timer.timeout.connect(self.scroll_motd)
        self.motd_timer.start(30)

        # ----------------- Slide Areas -----------------
        self.left_area = QWidget(self)
        self.right_area = QWidget(self)
        self.area_height = int(self.win_h * 0.70)
        self.left_area.setGeometry(int(0.05*self.win_w), int(0.15*self.win_h), int(0.40*self.win_w), self.area_height)
        self.right_area.setGeometry(int(0.55*self.win_w), int(0.15*self.win_h), int(0.40*self.win_w), self.area_height)

        # ----------------- Slide Timer -----------------
        self.slide_timer = QTimer()
        self.slide_timer.timeout.connect(self.next_slide)
        self.next_slide()  # show first slide

        # ----------------- Track labels & timers -----------------
        self.left_label = None
        self.right_label = None
        self.timer_left = None
        self.timer_right = None
        self.left_video_player = None
        self.right_video_player = None

    # ----------------- Slide Handling -----------------
    def next_slide(self):
        self.current_slide_index = (self.current_slide_index + 1) % len(self.slides)
        slide = self.slides[self.current_slide_index]
        print(f"[DEBUG] Showing slide {slide.get('id')}: {slide.get('title')}")
        title_area = slide.get("title_area") or "left"
        slide_title = slide.get("title")
        slide_title_style = slide.get("title_style")

        # Debug left/right content
        print(f"[DEBUG] Left content: {slide.get('left')}")
        print(f"[DEBUG] Right content: {slide.get('right')}")

        self.setup_side(self.left_area, slide.get("left"), side="left",
                        slide_title=slide_title if title_area=="left" else None,
                        slide_title_style=slide_title_style if title_area=="left" else None)
        self.setup_side(self.right_area, slide.get("right"), side="right",
                        slide_title=slide_title if title_area=="right" else None,
                        slide_title_style=slide_title_style if title_area=="right" else None)
        self.slide_timer.start(slide.get("duration",10)*1000)

    def setup_side(self, area, conf, side="left", slide_title=None, slide_title_style=None):
        # Stop previous timers
        if side=="left" and self.timer_left:
            self.timer_left.stop()
            self.timer_left = None
        if side=="right" and self.timer_right:
            self.timer_right.stop()
            self.timer_right = None

        # Clear children
        for child in area.children():
            child.deleteLater()

        if not conf:
            return

        title_height = 0
        # Title label
        if slide_title:
            font = slide_title_style.get("font","Arial") if slide_title_style else "Arial"
            size = slide_title_style.get("size",40) if slide_title_style else 40
            color = slide_title_style.get("color","#FFD700") if slide_title_style else "#FFD700"
            alignment = Qt.AlignmentFlag.AlignCenter
            align_str = slide_title_style.get("alignment","center").lower() if slide_title_style else "center"
            if align_str=="left": alignment = Qt.AlignmentFlag.AlignLeft
            if align_str=="right": alignment = Qt.AlignmentFlag.AlignRight
            title_label = QLabel(slide_title, area)
            title_label.setFont(QFont(font,size))
            title_label.setStyleSheet(f"color:{color}; background:transparent;")
            title_label.setGeometry(0,0,area.width(),size+20)
            title_label.setAlignment(alignment)
            title_label.show()
            title_height = size + 20

        # Content
        content_type = conf.get("type")
        source = conf.get("source")
        if not content_type or not source:
            return

        if content_type=="text":
            label = QLabel(source, area)
            label.setFont(QFont(conf.get("font","Arial"), conf.get("size",30)))
            label.setStyleSheet(f"color:{conf.get('color','#FFFFFF')};")
            label.setWordWrap(True)
            label.setGeometry(0, area.height(), area.width(), area.height())
            label.show()
            # Timer
            timer = QTimer(self)
            def scroll_label(label=label, timer=timer):
                if not label:
                    timer.stop()
                    return
                y = label.pos().y()
                if y > title_height:
                    label.move(label.pos().x(), y-2)
                else:
                    timer.stop()
            timer.timeout.connect(scroll_label)
            timer.start(30)
            if side=="left":
                self.left_label = label
                self.timer_left = timer
            else:
                self.right_label = label
                self.timer_right = timer

        elif content_type=="image":
            img_path = Path(source)
            if img_path.exists():
                pixmap = QPixmap(img_path).scaled(area.width(), self.area_height-title_height, Qt.AspectRatioMode.KeepAspectRatio)
                img_label = QLabel(area)
                img_label.setPixmap(pixmap)
                img_label.setGeometry(0,title_height,area.width(),self.area_height-title_height)
                img_label.show()
        elif content_type=="video":
            vid_path = Path(source)
            if vid_path.exists():
                video_widget = QVideoWidget(area)
                video_widget.setGeometry(0,title_height,area.width(),self.area_height-title_height)
                video_widget.show()
                player = QMediaPlayer(self)
                audio = QAudioOutput()
                player.setAudioOutput(audio)
                audio.setVolume(0.8)
                player.setVideoOutput(video_widget)
                player.setSource(QUrl.fromLocalFile(str(vid_path)))
                player.play()
                if side=="left":
                    self.left_video_player = player
                else:
                    self.right_video_player = player

    # ----------------- Clock -----------------
    def update_clock(self):
        if self.clock_label:
            now = QTime.currentTime()
            self.clock_label.setText(now.toString("HH:mm:ss"))

    # ----------------- MOTD -----------------
    def scroll_motd(self):
        self.ticker_x -= self.ticker_speed
        if self.ticker_x < -self.motd_label.width():
            self.ticker_x = int(self.win_w * 0.05)
        self.motd_label.move(self.ticker_x, self.ticker_y)

# ------------------ Main ------------------
def main():
    app = QApplication(sys.argv)
    config = get_config_from_server()
    config_changed = False
    if config:
        new_hash = hash_config(config)
        old_hash = load_config_hash()
        if new_hash != old_hash:
            print("[DEBUG] Config changed or first run. Updating cache and media.")
            config = ensure_media_files(config)
            save_config_cache(config)
            config_changed = True
        else:
            print("[DEBUG] Config unchanged. Using cached config and media.")
            config = load_config_cache()
    else:
        print("[WARNING] Server unreachable. Using cached config.")
        config = load_config_cache()
        if not config:
            print("[ERROR] No cached config available. Exiting.")
            sys.exit(1)

    settings = {
        "display_name": config.get("display_name"),
        "background_image": config.get("background_image"),
        "background_color": config.get("background_color"),
        "logo": config.get("logo"),
        "hide_logo": config.get("hide_logo", False),
        "clock": config.get("clock"),
    }
    motd_config = config.get("motd", {})
    slides_config = {"slides": config.get("slides", [])}

    window = MainWindow(slides_config, settings, motd_config)
    window.show()
    sys.exit(app.exec())

if __name__=="__main__":
    main()
