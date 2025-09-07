import sys
import yaml
import json
import hashlib
from pathlib import Path
import requests
from PyQt6.QtWidgets import QApplication, QWidget, QLabel
from PyQt6.QtCore import Qt, QTimer, QUrl
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

class MainWindow(QWidget):
    def __init__(self, slides_config, settings, motd_config):
        super().__init__()
        self.setWindowTitle(settings.get("display_name", "Display"))
        self.resize(1920, 1080)
        self.win_w, self.win_h = 1920, 1080

        # Background
        bg_path = settings.get("background_image")
        if bg_path and Path(bg_path).exists():
            pix = QPixmap(bg_path).scaled(self.win_w, self.win_h, Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            self.bg_label = QLabel(self)
            self.bg_label.setPixmap(pix)
            self.bg_label.setGeometry(0, 0, self.win_w, self.win_h)
            self.bg_label.lower()  # ensure background

        # Logo
        hide_logo = settings.get("hide_logo", False)
        logo_path = settings.get("logo")
        if not hide_logo and logo_path and Path(logo_path).exists():
            pix = QPixmap(logo_path)
            self.logo_label = QLabel(self)
            self.logo_label.setPixmap(pix)
            self.logo_label.setGeometry(10, 10, pix.width(), pix.height())
            self.logo_label.show()
        else:
            self.logo_label = None

        # Top label
        top_label_conf = settings.get("top_label", {})
        self.top_label = None
        if top_label_conf.get("text"):
            lbl = QLabel(top_label_conf.get("text"), self)
            lbl.setFont(QFont(top_label_conf.get("font","Arial"), top_label_conf.get("size",60)))
            lbl.setStyleSheet(f"color:{top_label_conf.get('color','#FFFFFF')}; background: transparent;")
            from_pct = top_label_conf.get("horizontal_from_percent",0)/100
            to_pct = top_label_conf.get("horizontal_to_percent",100)/100
            x = int(self.win_w * from_pct)
            w = int(self.win_w * (to_pct-from_pct))
            lbl.setGeometry(x, 10, w, lbl.fontMetrics().height())
            align_str = top_label_conf.get("alignment","left").lower()
            if align_str=="center":
                lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            elif align_str=="right":
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            else:
                lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
            lbl.show()
            self.top_label = lbl

       # MOTD horizontal scroller
        self.ticker_container = QWidget(self)
        self.ticker_container.setStyleSheet("background: transparent;")
        self.ticker_label = QLabel(motd_config.get("text", ""), self.ticker_container)
        self.ticker_label.setFont(QFont(motd_config.get("font","Arial"), motd_config.get("size",50)))
        self.ticker_label.setStyleSheet(f"color:{motd_config.get('color','#FFFFFF')}; background: transparent;")
        self.ticker_label.setWordWrap(False)

        # calculate container geometry from percent
        from_pct = motd_config.get("horizontal_from_percent",0)/100
        to_pct = motd_config.get("horizontal_to_percent",100)/100
        x = int(self.win_w * from_pct)
        w = int(self.win_w * (to_pct-from_pct))
        ticker_y = int(self.win_h * motd_config.get("height_percent",90)/100)
        self.ticker_container.setGeometry(x, ticker_y, w, self.ticker_label.fontMetrics().height())

        # prepare repeated text with spaces for seamless loop
        repeat_text = self.ticker_label.text() + "     "
        self.ticker_label.setText(repeat_text * 20)  # repeat enough times
        self.ticker_label.adjustSize()

        # initial position: start at the right edge of container
        self.ticker_x = w
        self.ticker_label.move(self.ticker_x, 0)

        self.ticker_speed = motd_config.get("speed",3)
        self.ticker_timer = QTimer()
        def scroll_label():
            self.ticker_x -= self.ticker_speed
            if self.ticker_x < -self.ticker_label.width()//2:
                self.ticker_x = w  # reset to start at container right edge
            self.ticker_label.move(self.ticker_x, 0)

        self.ticker_timer.timeout.connect(scroll_label)
        self.ticker_timer.start(30)

        # Slide areas
        self.left_area = QWidget(self)
        self.right_area = QWidget(self)
        self.area_height = int(self.win_h * 0.7)
        self.left_area.setGeometry(int(0.05*self.win_w), int(0.15*self.win_h), int(0.4*self.win_w), self.area_height)
        self.right_area.setGeometry(int(0.55*self.win_w), int(0.15*self.win_h), int(0.4*self.win_w), self.area_height)
        self.left_area.setStyleSheet("background: transparent;")
        self.right_area.setStyleSheet("background: transparent;")
        self.left_area.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.right_area.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.slides = slides_config.get("slides", [])
        self.current_slide_index = -1
        self.timer_left = None
        self.timer_right = None
        self.left_label = None
        self.right_label = None

        self.slide_timer = QTimer()
        self.slide_timer.timeout.connect(self.next_slide)
        self.next_slide()  # first slide

    def next_slide(self):
        if self.timer_left:
            self.timer_left.stop()
            self.timer_left.deleteLater()
            self.timer_left = None
            self.left_label = None
        if self.timer_right:
            self.timer_right.stop()
            self.timer_right.deleteLater()
            self.timer_right = None
            self.right_label = None

        self.current_slide_index = (self.current_slide_index + 1) % len(self.slides)
        slide = self.slides[self.current_slide_index]
        print(f"[DEBUG] Showing slide {slide.get('id')}: {slide.get('title')}")

        for area in [self.left_area, self.right_area]:
            for child in area.children():
                child.deleteLater()

        # static slide title
        slide_title = slide.get("title")
        title_area = slide.get("title_area","left")
        title_style = slide.get("title_style", {})
        if slide_title:
            lbl = QLabel(slide_title, self.left_area if title_area=="left" else self.right_area)
            lbl.setFont(QFont(title_style.get("font","Arial"), title_style.get("size",40)))
            lbl.setStyleSheet(f"color:{title_style.get('color','#FFFFFF')}; background: transparent;")
            lbl.adjustSize()
            lbl.move((self.left_area.width() - lbl.width())//2 if title_area=="left" else (self.right_area.width()-lbl.width())//2, 0)
            lbl.show()

        self.setup_side(self.left_area, slide.get("left"), side="left")
        self.setup_side(self.right_area, slide.get("right"), side="right")

        duration = slide.get("duration",10)*1000
        self.slide_timer.start(duration)

    def setup_side(self, area, conf, side="left"):
        if not conf:
            return
        ctype = conf.get("type")
        source = conf.get("source")

        if ctype=="text" and source:
            label = QLabel(source, area)
            label.setFont(QFont(conf.get("font","Arial"), conf.get("size",40)))
            label.setStyleSheet(f"color:{conf.get('color','#FFFFFF')}; background: transparent;")
            label.setWordWrap(True)
            label.adjustSize()
            label.move(0, area.height())
            label.show()
            timer = QTimer()
            def scroll():
                if not label or not label.isVisible():
                    timer.stop()
                    return
                x, y = label.pos().x(), label.pos().y()
                if y>0:
                    label.move(x, y-2)
                else:
                    timer.stop()
            timer.timeout.connect(scroll)
            timer.start(30)
            if side=="left":
                self.timer_left = timer
                self.left_label = label
            else:
                self.timer_right = timer
                self.right_label = label

        elif ctype=="image" and source and Path(source).exists():
            pix = QPixmap(source).scaled(area.width(), self.area_height, Qt.AspectRatioMode.KeepAspectRatio)
            label = QLabel(area)
            label.setPixmap(pix)
            label.setStyleSheet("background: transparent;")
            label.setGeometry(0,0,pix.width(), pix.height())
            label.show()

        elif ctype=="video" and source and Path(source).exists():
            video_widget = QVideoWidget(area)
            video_widget.setGeometry(0,0,area.width(), self.area_height)
            video_widget.show()
            player = QMediaPlayer()
            audio = QAudioOutput()
            player.setAudioOutput(audio)
            audio.setVolume(0.8)
            player.setVideoOutput(video_widget)
            player.setSource(QUrl.fromLocalFile(str(source)))
            player.play()

    def scroll_label(self):
        if self.ticker_label:
            self.ticker_x -= self.ticker_speed
            if self.ticker_x < -self.ticker_label.width()//2:
                self.ticker_x = 0
            self.ticker_label.move(self.ticker_x,0)

def main():
    app = QApplication(sys.argv)

    config = get_config_from_server()
    if config:
        new_hash = hash_config(config)
        old_hash = load_config_hash()
        if new_hash != old_hash:
            config = ensure_media_files(config)
            save_config_cache(config)
            print("[DEBUG] Config changed or first run. Updating cache and media.")
        else:
            config = load_config_cache()
            print("[DEBUG] Config unchanged. Using cached config.")
    else:
        config = load_config_cache()
        if not config:
            print("[ERROR] No cached config and server unreachable. Exiting.")
            sys.exit(1)
        print("[WARNING] Server unreachable. Using cached config.")

    slides_config = {"slides": config.get("slides",[])}
    settings = config
    motd_config = config.get("motd", {})

    window = MainWindow(slides_config, settings, motd_config)
    window.show()
    sys.exit(app.exec())

if __name__=="__main__":
    main()
