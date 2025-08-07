# main.py
# M5Stack Cardputer 莫斯电码翻译器
# 最终生产版 - 采用统一的M5.Lcd渲染，修复所有UI冲突和状态问题

import M5
from M5 import Speaker
from hardware.matrix_keyboard import MatrixKeyboard
import time

# --- [1] 状态机和全局变量 ---
output_string = "Ready."
last_input_display_string = ""  # 用于存储上一次输入内容的全局变量

# 定义动作列表
ACTIONS = ["Switch Mode", "Play Demo", "Speaker", "Presets"]

# 键盘和状态
kb = None
last_key_state = False

# 应用状态
MODES = ["Text -> Morse", "Morse -> Text"]
current_mode_index = 0
input_string = ""
last_morse_output = ""
speaker_on = False

# 模态UI的状态
is_menu_active = False
options_menu = None
is_selecting_preset = False
preset_list = None

# 预设
PRESETS = {
    "SOS": "... --- ...",
    "CQ": "-.-. --.-",
    "73": "--... ...--",
    "HELLO": ".... . .-.. .-.. ---",
    "QTH?": "--.- - .... ..--..",
    "MY NAME IS": "-- -.-- / -. .- -- . / .. ...",
}
PRESET_KEYS = list(PRESETS.keys())

# 莫斯电码字典 (保持不变)
CHAR_TO_MORSE = {
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.', 'G': '--.', 'H': '....',
    'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..', 'M': '--', 'N': '-.', 'O': '---', 'P': '.--.',
    'Q': '--.-', 'R': '.-.', 'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
    'Y': '-.--', 'Z': '--..', '1': '.----', '2': '..---', '3': '...--', '4': '....-', '5': '.....',
    '6': '-....', '7': '--...', '8': '---..', '9': '----.', '0': '-----',
    '.': '.-.-.-', ',': '--..--', '?': '..--..', "'": '.----.', '!': '-.-.--', '/': '-..-.',
    '(': '-.--.', ')': '-.--.-', '&': '.-...', ':': '---...', ';': '-.-.-.', '=': '-...-',
    '+': '.-.-.', '-': '-....-', '_': '..--.-', '"': '.-..-.', '$': '...-..-', '@': '.--.-.'
}
MORSE_TO_CHAR = {v: k for k, v in CHAR_TO_MORSE.items()}


# --- [2] UI类定义 ---

class OptionsMenu:
    """一个功能齐全的、可复用的模态选项菜单。"""

    def __init__(self, x, y, w, h, items, title=""):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.items = items
        self.title = title
        self.selected_index = 0
        self.visible = False
        self.dirty = True  # [闪烁修复] 新增脏标记
        # 采用您调整后的颜色定义
        self.bg_color = 0xffffff
        self.border_color = 0xffffff
        self.text_color = 0x222222
        self.selected_bg_color = 0xc2bcbc
        self.selected_text_color = 0xffffff
        self.title_bg_color = 0xc2bcbc

    def show(self):
        self.visible = True
        self.selected_index = 0
        self.dirty = True  # [闪烁修复] 显示时标记为需要重绘

    def hide(self):
        self.visible = False

    def handle_key(self, key_str):
        """处理按键输入，返回选择结果或'close'。"""
        if not self.visible:
            return None

        # 采用您修复后的方向键逻辑
        if key_str == ';':  # 分号键，作为“向上”
            self.selected_index = (self.selected_index - 1 + len(self.items)) % len(self.items)
            self.dirty = True  # [闪烁修复] 选择变化时标记为需要重绘
        elif key_str == '.':  # 句号键，作为“向下”
            self.selected_index = (self.selected_index + 1) % len(self.items)
            self.dirty = True  # [闪烁修复] 选择变化时标记为需要重绘
        elif key_str in ('enter', '\r'):
            return self.items[self.selected_index]
        # [最终修正] 同时处理 ` 和 \x1b 作为退出键
        elif key_str in ('`', '\x1b'):
            self.hide()
            return 'close'
        return None

    def draw(self):
        """完全使用 M5.Lcd API 手动绘制，稳定可靠。"""
        if not self.visible or not self.dirty:  # [闪烁修复] 仅在需要时重绘
            return

        M5.Lcd.fillRect(self.x, self.y, self.w, self.h, self.bg_color)
        M5.Lcd.drawRect(self.x, self.y, self.w, self.h, self.border_color)
        M5.Lcd.fillRect(self.x + 1, self.y + 1, self.w - 2, 22, self.title_bg_color)
        M5.Lcd.setTextSize(2)
        M5.Lcd.setTextColor(self.text_color, self.title_bg_color)
        M5.Lcd.setCursor(self.x + 5, self.y + 5)
        M5.Lcd.print(self.title)

        item_y = self.y + 30
        for i, item_text in enumerate(self.items):
            # 动态生成扬声器状态文本
            if item_text == "Speaker":
                display_text = f"Speaker: {'ON' if speaker_on else 'OFF'}"
            else:
                display_text = item_text

            if i == self.selected_index:
                M5.Lcd.fillRect(self.x + 2, item_y - 2, self.w - 4, 20, self.selected_bg_color)
                M5.Lcd.setTextColor(self.selected_text_color, self.selected_bg_color)
            else:
                M5.Lcd.setTextColor(self.text_color, self.bg_color)

            M5.Lcd.setCursor(self.x + 10, item_y)
            M5.Lcd.print(display_text)
            item_y += 25
            if item_y > self.y + self.h - 15:  # 增加边界检查
                break

        self.dirty = False  # [闪烁修复] 重绘后清除标记


class PresetList(OptionsMenu):
    """专门用于预设选择的列表，干净地继承自OptionsMenu。"""
    pass


# --- [3] 核心函数 ---

def redraw_ui():
    """一个统一的重绘函数，用于在关闭菜单或播放后恢复界面"""
    # [最终修正] 使用 M5.Lcd.fillScreen 并手动重绘所有元素
    M5.Lcd.fillScreen(0xffffff)

    # --- 绘制所有主UI元素 ---
    M5.Lcd.setTextSize(2)

    # 绘制上一次的输入
    M5.Lcd.setTextColor(0x888888, 0xffffff)
    M5.Lcd.setCursor(8, 20)
    M5.Lcd.print(last_input_display_string)

    # 绘制输出结果
    M5.Lcd.setTextColor(0x000000, 0xffffff)
    words = output_string.split(' ')
    lines = []
    current_line = ""
    for word in words:
        test_line = (current_line + " " + word).strip()
        if M5.Lcd.textWidth(test_line) <= 280:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    draw_y = 40
    for line in lines:
        M5.Lcd.setCursor(8, draw_y)
        M5.Lcd.print(line)
        draw_y += 18
        if draw_y > 75: break

    # 绘制当前模式
    M5.Lcd.setTextColor(0x000000, 0xffffff)
    M5.Lcd.setCursor(8, 80)
    M5.Lcd.print(MODES[current_mode_index])

    # 绘制当前输入行
    M5.Lcd.setTextColor(0x000000, 0xffffff)
    M5.Lcd.setCursor(8, 96)
    M5.Lcd.print(">" + input_string)


def setup():
    global kb, options_menu, preset_list
    M5.begin()

    # 初始化模态菜单
    options_menu = OptionsMenu(60, 10, 160, 115, ACTIONS, title="Options")
    preset_list = PresetList(40, 10, 160, 115, PRESET_KEYS, title="Presets")

    # 初始化键盘
    kb = MatrixKeyboard()

    # 首次绘制UI
    redraw_ui()


def translate():
    """翻译核心函数"""
    global input_string, last_morse_output, output_string, last_input_display_string

    if input_string:
        last_input_display_string = f"In: {input_string[:25]}"
    else:
        last_input_display_string = ""

    mode = MODES[current_mode_index]
    translated_text = ""
    if mode == "Text -> Morse":
        text_to_translate = input_string.upper()
        morse_result = [CHAR_TO_MORSE.get(c, '?' if c != ' ' else '/') for c in text_to_translate]
        translated_text = " ".join(morse_result)
    elif mode == "Morse -> Text":
        morse_words = input_string.split('/')
        text_result = []
        for word in morse_words:
            letters = word.strip().split(' ')
            for code in letters:
                if code: text_result.append(MORSE_TO_CHAR.get(code, '?'))
            text_result.append(' ')
        translated_text = "".join(text_result).strip()

    last_morse_output = translated_text.replace('/', ' ')
    output_string = translated_text
    input_string = ""

    redraw_ui()


def play_morse():
    """播放莫斯电码声音，并同步屏幕闪烁"""
    global last_morse_output
    if not last_morse_output: return

    # 播放前先隐藏主UI，避免视觉混乱
    M5.Lcd.fillScreen(0x000000)

    for symbol in last_morse_output:
        duration = 0
        if symbol == '.':
            duration = 80
        elif symbol == '-':
            duration = 240

        if duration > 0:
            if speaker_on: Speaker.tone(800, duration)
            time.sleep_ms(duration)
            if speaker_on: Speaker.noTone()
            time.sleep_ms(80)  # 音调间的间隔
        elif symbol == ' ':
            time.sleep_ms(160)  # 字符间的间隔

    redraw_ui()  # 播放结束后重绘整个UI

def handle_input():
    """处理所有键盘输入和功能逻辑"""
    global last_key_state, input_string, current_mode_index, speaker_on, output_string
    global is_menu_active, is_selecting_preset

    is_key_down = False
    try:
        kb.tick()
        is_key_down = kb.is_pressed()
    except Exception:
        pass

    if is_key_down and not last_key_state:
        key_string = kb.get_string()
        if key_string:
            # 模态输入处理
            if is_menu_active:
                action = options_menu.handle_key(key_string)
                if action == 'close':
                    is_menu_active = False
                    redraw_ui()
                elif action == "Switch Mode":
                    current_mode_index = (current_mode_index + 1) % len(MODES)
                    is_menu_active = False
                    redraw_ui()
                elif action == "Play Demo":
                    is_menu_active = False
                    play_morse() # 直接播放，播放完会自动重绘
                elif action == "Speaker":
                    speaker_on = not speaker_on
                    options_menu.dirty = True  # [闪烁修复] 状态改变，标记菜单需要重绘
                elif action == "Presets":
                    is_menu_active = False
                    is_selecting_preset = True
                    preset_list.show()

            elif is_selecting_preset:
                preset = preset_list.handle_key(key_string)
                if preset == 'close':
                    is_selecting_preset = False
                    redraw_ui()
                elif preset:
                    input_string = preset
                    is_selecting_preset = False
                    redraw_ui() # 选择预设后重绘主界面

            else:
                # --- 正常模式下的输入处理 ---
                if key_string == '\t':
                    is_menu_active = True
                    options_menu.show()
                elif key_string in ('enter', '\r'):
                    translate()
                elif key_string == '\x08':  # 删除键
                    input_string = input_string[:-1]
                    redraw_ui() # 删除字符后也需要重绘输入行
                else:  # 其他所有可打印字符
                    input_string += key_string
                    redraw_ui() # 输入字符后也需要重绘输入行

    last_key_state = is_key_down


def loop():
    M5.update()
    handle_input()

    # [闪烁修复] 仅在需要时绘制模态UI
    if is_menu_active:
        options_menu.draw()
    elif is_selecting_preset:
        preset_list.draw()


if __name__ == '__main__':
    try:
        setup()
        while True:
            loop()
    except (Exception, KeyboardInterrupt) as e:
        try:
            from utility import print_error_msg
            print_error_msg(e)
        except ImportError:
            print("please update to latest firmware")