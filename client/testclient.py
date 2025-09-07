import sys
import yaml
import random
import requests
import hashlib
import json
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QWidget, QLabel
from PyQt6.QtCore import Qt, QTimer, QUrl, QTime
from PyQt6.QtGui import QFont, QPixmap, QPalette, QColor
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

SERVER_URL = "http://localhost:5000"
CLIENT_ID = "testclient"
CACHE_DIR = Path(__file__).parent / "cache"
MEDIA_DIR = CACHE_DIR / "media"
CONFIG_CACHE_FILE = CACHE_DIR / "config.json"
CONFIG_HASH_FILE = CACHE_DIR / "config_hash.txt"

CACHE_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)

def get_config_from_server():
    try:
        resp = requests.get(f"{SERVER_URL}/config/{CLIENT_ID}", timeout=5)
        resp.raise_for_status()
        config = resp.json()
        return config
    except Exception as e:
        print(f"Could not fetch config from server: {e}")
        return None

def hash_config(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()

def save_config_cache(config):
    with open(CONFIG_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f)
    with open(CONFIG_HASH_FILE, "w") as f:
        f.write(hash_config(config))

def load_config_cache():
    if CONFIG_CACHE_FILE.exists():
        with open(CONFIG_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def load_config_hash():
    if CONFIG_HASH_FILE.exists():
        with open(CONFIG_HASH_FILE, "r") as f:
            return f.read().strip()
    return None

def download_media(url, filename):
    local_path = MEDIA_DIR / filename
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(resp.content)
        print(f"Downloaded {filename}")
    except Exception as e:
        print(f"Failed to download {filename}: {e}")
    return local_path

def ensure_media_files(config):
    # Collect all media URLs and local filenames
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

class MainWindow(QWidget):
    def __init__(self, slides_config, settings, base_path, motd_config):
        super().__init__()
        self.setWindowTitle(settings.get("display_name", ""))
        self.resize(1920, 1080)
        self.win_w, self.win_h = 1920, 1080

        self.slides = slides_config.get("slides", [])
        self.current_slide_index = -1
        self.base_path = base_path

        # ----------------- Background -----------------
        bg_color = settings.get("background_color", "#000000")
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(bg_color))
        self.setAutoFillBackground(True)
        self.setPalette(palette)

        bg_img_path = settings.get("background_image")
        if bg_img_path:
            bg_img_path = Path(bg_img_path)
            if bg_img_path.exists():
                bg_pixmap = QPixmap(str(bg_img_path))
                self.bg_label = QLabel(self)
                self.bg_label.setPixmap(bg_pixmap.scaled(self.win_w, self.win_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.bg_label.setGeometry(0, 0, self.win_w, self.win_h)
                self.bg_label.lower()
                self.bg_label.show()

        # ----------------- Logo or Logo Text -----------------
        logo_path = settings.get("logo")
        logo_text_conf = settings.get("logo_text")
        self.logo_label = None

        if logo_path:
            logo_path = Path(logo_path)
            if logo_path.exists():
                self.logo_label = QLabel(self)
                pixmap = QPixmap(str(logo_path)).scaledToHeight(int(self.win_h * 0.11))
                self.logo_label.setPixmap(pixmap)
                self.logo_label.move(int(0.02 * self.win_w), int(0.02 * self.win_h))
                self.logo_label.show()
        elif logo_text_conf:
            text = logo_text_conf.get("text", "")
            font = logo_text_conf.get("font", "Arial")
            size = logo_text_conf.get("size", 48)
            color = logo_text_conf.get("color", "#FFFFFF")
            top_pct = logo_text_conf.get("top_percent", 3)
            left_pct = logo_text_conf.get("left_percent", 2)
            self.logo_label = QLabel(text, self)
            self.logo_label.setFont(QFont(font, size))
            self.logo_label.setStyleSheet(f"color: {color}; background: transparent;")
            self.logo_label.adjustSize()
            self.logo_label.move(int(left_pct * self.win_w / 100), int(top_pct * self.win_h / 100))
            self.logo_label.show()

        # ----------------- Clock (optional) -----------------
        clock_conf = settings.get("clock", {})
        clock_enabled = clock_conf.get("enabled", True)  # Default: show clock

        if clock_enabled:
            clock_font = clock_conf.get("font", "Arial")
            clock_color = clock_conf.get("color", "#FFFFFF")
            clock_from_h = int(clock_conf.get("from_h", 2) * self.win_h / 100)
            clock_to_h = int(clock_conf.get("to_h", 13) * self.win_h / 100)
            clock_from_w = int(clock_conf.get("from_w", 80) * self.win_w / 100)
            clock_to_w = int(clock_conf.get("to_w", 98) * self.win_w / 100)

            self.clock_label = QLabel(self)
            self.clock_label.setFont(QFont(clock_font, 32))
            self.clock_label.setStyleSheet(f"color: {clock_color};")
            self.clock_label.setGeometry(clock_from_w, clock_from_h,
                                         clock_to_w - clock_from_w, clock_to_h - clock_from_h)
            self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.clock_label.show()

            self.clock_timer = QTimer()
            self.clock_timer.timeout.connect(self.update_clock)
            self.clock_timer.start(1000)
            self.update_clock()
        else:
            self.clock_label = None
            self.clock_timer = None

        # ----------------- Horizontal Ticker -----------------
        motd_text = motd_config.get("text", "")
        motd_font = motd_config.get("font", "Arial")
        motd_size = motd_config.get("size", 24)
        motd_color = motd_config.get("color", "FFFFFF")
        motd_y_pct = motd_config.get("height_percent", 90)
        motd_start = motd_config.get("horizontal_from_percent", 5)/100
        motd_end = motd_config.get("horizontal_to_percent", 95)/100

        ticker_height = motd_size + 12  # 12px padding, adjust as needed
        self.ticker_speed = motd_config.get("speed", 3)

        # Create ticker container
        self.ticker_left_limit = int(self.win_w * motd_start)
        self.ticker_right_limit = int(self.win_w * motd_end)
        self.ticker_y = int(self.win_h * motd_y_pct / 100)
        self.ticker_width = self.ticker_right_limit - self.ticker_left_limit

        self.ticker_container = QWidget(self)
        self.ticker_container.setGeometry(self.ticker_left_limit, self.ticker_y, self.ticker_width, ticker_height)
        self.ticker_container.setStyleSheet("background: transparent;")
        self.ticker_container.show()

        self.ticker_label = QLabel(motd_text, self.ticker_container)
        self.ticker_label.setFont(QFont(motd_font, motd_size))
        self.ticker_label.setStyleSheet(f"color: {motd_color}; background: transparent;")
        self.ticker_label.adjustSize()
        self.ticker_x = self.ticker_width
        self.ticker_label.move(self.ticker_x, 0)
        self.ticker_label.show()
        self.ticker_label.raise_()

        self.ticker_timer = QTimer()
        self.ticker_timer.timeout.connect(self.scroll_ticker)
        self.ticker_timer.start(30)

        # ----------------- Slide Areas -----------------
        self.left_area = QWidget(self)
        self.right_area = QWidget(self)
        self.area_height = int(self.win_h * 0.70)  # 15% to 85%
        self.left_area.setGeometry(int(0.05 * self.win_w), int(0.15 * self.win_h),
                                   int(0.40 * self.win_w), self.area_height)
        self.right_area.setGeometry(int(0.55 * self.win_w), int(0.15 * self.win_h),
                                    int(0.40 * self.win_w), self.area_height)

        # ----------------- Slide Timer -----------------
        self.slide_timer = QTimer()
        self.slide_timer.timeout.connect(self.next_slide)
        self.next_slide()  # first slide

        # ----------------- Burn-in Protection -----------------
        self.blank_overlay = QWidget(self)
        self.blank_overlay.setStyleSheet("background-color: black;")
        self.blank_overlay.setGeometry(0, 0, self.win_w, self.win_h)
        self.blank_overlay.hide()

        burnin_conf = settings.get("burnin", None)
        if burnin_conf:
            self.burnin_mode = burnin_conf.get("mode", "blank")
            self.burnin_duration = int(burnin_conf.get("duration_ms", 200))
            interval = int(burnin_conf.get("interval_sec", 300)) * 1000
            self.burnin_timer = QTimer()
            self.burnin_timer.timeout.connect(self.apply_burnin_protection)
            self.burnin_timer.start(interval)
        else:
            self.burnin_mode = None

    # ----------------- Slide Handling -----------------
    def next_slide(self):
        self.current_slide_index = (self.current_slide_index + 1) % len(self.slides)
        slide = self.slides[self.current_slide_index]

        print(f"\n--- Showing Slide {slide.get('id')} ---")
        print(yaml.dump(slide, sort_keys=False))

        slide_title = slide.get("title", "")
        slide_title_style = slide.get("title_style", {})
        title_area = slide.get("title_area", None)
        if not title_area:
            if slide.get("left", {}).get("type") == "text":
                title_area = "left"
            else:
                title_area = "right"

        self.setup_side(self.left_area, slide.get("left"), self.area_height, side="left",
                        slide_title=slide_title if title_area == "left" else None,
                        slide_title_style=slide_title_style if title_area == "left" else None)
        self.setup_side(self.right_area, slide.get("right"), self.area_height, side="right",
                        slide_title=slide_title if title_area == "right" else None,
                        slide_title_style=slide_title_style if title_area == "right" else None)

        duration = slide.get("duration", 10) * 1000
        self.slide_timer.start(duration)

    def setup_side(self, area, conf, area_height, side="left", slide_title=None, slide_title_style=None):
        # Stop and clear previous scrolling label and timer
        if side == "left":
            if hasattr(self, "timer_left") and self.timer_left.isActive():
                self.timer_left.stop()
            self.left_label = None
        else:
            if hasattr(self, "timer_right") and self.timer_right.isActive():
                self.timer_right.stop()
            self.right_label = None

        # clear widgets
        for child in area.children():
            child.deleteLater()
        area.update()

        title_height = 0

        # Add slide title label if provided
        if slide_title:
            # Default styles
            font = "Arial"
            size = 40
            color = "#FFD700"
            alignment = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter

            # Override from style dict
            if slide_title_style:
                font = slide_title_style.get("font", font)
                size = slide_title_style.get("size", size)
                color = slide_title_style.get("color", color)
                align_str = slide_title_style.get("alignment", "center").lower()
                if align_str == "left":
                    alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                elif align_str == "right":
                    alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                else:
                    alignment = Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter

            title_label = QLabel(slide_title, area)
            title_label.setFont(QFont(font, size))
            title_label.setStyleSheet(f"color: {color}; background: transparent;")
            title_label.setGeometry(0, 0, area.width(), size + 20)
            title_label.setAlignment(alignment)
            title_label.show()
            title_label.raise_()
            title_height = size + 20

        if conf is None: return
        content_type = conf.get("type")
        source = conf.get("source")
        if content_type is None or source is None: return

        # --- Add static title label if present in area config ---
        area_title_text = conf.get("title", "")
        area_title_label = None
        if area_title_text:
            area_title_label = QLabel(area_title_text, area)
            area_title_label.setFont(QFont("Arial", 32))
            area_title_label.setStyleSheet("color: #FFD700; background: transparent;")
            area_title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            area_title_label.adjustSize()
            area_title_label.move(0, title_height)
            area_title_label.show()
            area_title_label.raise_()
            title_height += area_title_label.height() + 10  # 10px padding

        if content_type == "text":
            font_name = conf.get("font", "Arial")
            font_size = conf.get("size", 40)
            color = conf.get("color", "#FFFFFF")
            label = QLabel(source, area)
            label.setFont(QFont(font_name, font_size))
            label.setStyleSheet(f"color: {color};")
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            label.setWordWrap(True)
            label.setFixedWidth(area.width())
            label.adjustSize()

            start_y = area.height()
            end_y = title_height  # Start scrolling below the title(s)
            label.move(0, start_y)
            label.show()

            timer = QTimer()
            if side == "left":
                self.left_label = label
                self.end_y_label = end_y
                self.timer_left = timer
                self.timer_left.timeout.connect(self.scroll_text_left)
                self.timer_left.start(30)
            else:
                self.right_label = label
                self.end_y_right = end_y
                self.timer_right = timer
                self.timer_right.timeout.connect(self.scroll_text_right)
                self.timer_right.start(30)

        elif content_type == "image":
            img_path = Path(source)
            if img_path.exists():
                pixmap = QPixmap(str(img_path))
                img_label = QLabel(area)
                img_label.setPixmap(pixmap.scaled(area.width(), area_height,
                                                  Qt.AspectRatioMode.KeepAspectRatio))
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_label.move(0, title_height)
                img_label.show()
                if side=="left": self.left_img_label = img_label
                else: self.right_img_label = img_label

        elif content_type == "video":
            vid_path = Path(source)
            if vid_path.exists():
                video = QVideoWidget(area)
                video.setGeometry(0, title_height, area.width(), area_height-title_height)
                video.show()
                player = QMediaPlayer(self)
                audio = QAudioOutput()
                player.setAudioOutput(audio)
                audio.setVolume(0.8)
                player.setVideoOutput(video)
                player.setSource(QUrl.fromLocalFile(str(vid_path)))
                player.play()
                if side=="left": self.left_video_player,self.left_video_widget = player,video
                else: self.right_video_player,self.right_video_widget = player,video

    # ----------------- Animations -----------------
    def scroll_text_left(self):
        if not hasattr(self,"left_label") or self.left_label is None: return
        x,y = self.left_label.pos().x(),self.left_label.pos().y()
        if y>self.end_y_label: self.left_label.move(x,y-2)
        else: self.timer_left.stop()

    def scroll_text_right(self):
        if not hasattr(self,"right_label") or self.right_label is None: return
        x,y = self.right_label.pos().x(),self.right_label.pos().y()
        if y>self.end_y_right: self.right_label.move(x,y-2)
        else: self.timer_right.stop()

    def scroll_ticker(self):
        self.ticker_x -= self.ticker_speed
        if self.ticker_x < -self.ticker_label.width():
            self.ticker_x = self.ticker_width
        self.ticker_label.move(self.ticker_x, 0)
        self.ticker_label.raise_()  # ensure always visible

    def update_clock(self):
        now = QTime.currentTime()
        self.clock_label.setText(now.toString("HH:mm:ss"))

    def apply_burnin_protection(self):
        if self.burnin_mode=="blank":
            self.blank_overlay.show()
            QTimer.singleShot(self.burnin_duration, self.blank_overlay.hide)
            # Ensure ticker/clock/logo remain visible
            self.clock_label.raise_()
            if self.logo_label: self.logo_label.raise_()
            self.ticker_label.raise_()
        elif self.burnin_mode=="shift":
            max_shift = 10
            for widget in [self.clock_label,self.logo_label]:
                if widget and widget.isVisible():
                    geo = widget.geometry()
                    dx=random.randint(-max_shift,max_shift)
                    dy=random.randint(-max_shift,max_shift)
                    widget.move(max(0,min(self.win_w-geo.width(),geo.x()+dx)),
                                max(0,min(self.win_h-geo.height(),geo.y()+dy)))

# ---------------- Main ----------------
def main():
    app = QApplication(sys.argv)
    config = get_config_from_server()
    config_changed = False

    if config:
        new_hash = hash_config(config)
        old_hash = load_config_hash()
        if new_hash != old_hash:
            print("Config changed or first run. Updating cache and media.")
            config = ensure_media_files(config)
            save_config_cache(config)
            config_changed = True
        else:
            print("Config unchanged. Using cached config and media.")
            config = load_config_cache()
    else:
        print("Server unreachable. Using cached config and media.")
        config = load_config_cache()
        if not config:
            print("No cached config available. Exiting.")
            sys.exit(1)

    # Extract settings and motd from config
    settings = {
        "display_name": config.get("display_name"),
        "background_image": config.get("background_image"),
        "background_color": config.get("background_color"),
        "logo": config.get("logo"),
        "logo_text": config.get("logo_text"),
        "clock": config.get("clock"),
        "burnin": config.get("burnin"),
    }
    motd_config = config.get("motd", {})
    slides_config = {"slides": config.get("slides", [])}

    window = MainWindow(slides_config, settings, MEDIA_DIR, motd_config)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
