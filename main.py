# main.py
# M5Stack Cardputer 莫斯电码翻译器
# 最终生产版 - 修复了菜单闪烁、按键逻辑、焦点问题并新增了输入比对功能

import M5
from M5 import Widgets, Speaker
from hardware.matrix_keyboard import MatrixKeyboard
import time


# --- [1] 状态机和全局变量 ---
output_string = "Ready."

# 定义动作列表
ACTIONS = ["Switch Mode", "Play Demo", "Speaker", "Presets"]

# UI元素
current_mode_label = None
input_label = None
last_input_label = None # 新增：用于显示上一次输入的标签

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
        # 颜色定义
        self.bg_color = 0x2c2c2c
        self.border_color = 0xaaaaaa
        self.text_color = 0xffffff
        self.selected_bg_color = 0x007acc
        self.selected_text_color = 0xffffff
        self.title_bg_color = 0x4a4a4a

    def show(self):
        self.visible = True
        self.selected_index = 0

    def hide(self):
        self.visible = False

    def handle_key(self, key_str):
        """处理按键输入，返回选择结果或'close'。"""
        if not self.visible:
            return None

        # [修正] 您的方向键修复是正确的
        if key_str == ';':  # 分号键，作为“向上”
            self.selected_index = (self.selected_index - 1 + len(self.items)) % len(self.items)
        elif key_str == '.':  # 句号键，作为“向下”
            self.selected_index = (self.selected_index + 1) % len(self.items)
        elif key_str in ('enter', '\r'):
            return self.items[self.selected_index]
        # [问题1修正] 同时处理 ` 和 \x1b 作为退出键
        elif key_str in ('`', '\x1b'):
            self.hide()
            return 'close'
        return None

    def draw(self):
        """完全使用 M5.Lcd API 手动绘制，稳定可靠。"""
        if not self.visible:
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
            if item_y > self.y + self.h - 15: # 增加边界检查
                break


class PresetList(OptionsMenu):
    """专门用于预设选择的列表，干净地继承自OptionsMenu。"""
    pass


# --- [3] 核心函数 ---

def draw_output_text(text_to_draw):
    """使用底层Lcd API手动绘制带有换行的输出文本"""
    M5.Lcd.fillRect(8, 35, 280, 45, 0xffffff) # 清除输出区域
    M5.Lcd.setTextSize(2)
    M5.Lcd.setTextColor(0x000000)
    words = text_to_draw.split(' ')
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
    draw_y = 35
    for line in lines:
        M5.Lcd.setCursor(8, draw_y)
        M5.Lcd.print(line)
        draw_y += 18
        if draw_y > 75: break


def setup():
    global current_mode_label, input_label, last_input_label, kb, options_menu, preset_list
    M5.begin()
    Widgets.fillScreen(0xffffff)

    # --- 初始化UI ---
    # 左侧核心显示区
    last_input_label = Widgets.Label("", 8, 20, 1.0, 0x888888, 0xffffff, Widgets.FONTS.DejaVu18)
    current_mode_label = Widgets.Label(MODES[0], 8, 80, 1.0, 0x000000, 0xffffff, Widgets.FONTS.DejaVu18)
    input_label = Widgets.Label(">", 8, 96, 1.0, 0x000000, 0xffffff, Widgets.FONTS.DejaVu18)
    draw_output_text(output_string)

    # 初始化模态菜单，并传入对应的项目列表
    options_menu = OptionsMenu(80, 10, 160, 115, ACTIONS, title="Options")
    preset_list = PresetList(80, 10, 160, 115, PRESET_KEYS, title="Presets")

    # 初始化键盘
    kb = MatrixKeyboard()


def redraw_ui():
    """一个统一的重绘函数，用于在关闭菜单或播放后恢复界面"""
    M5.Lcd.fillRect(0, 0, 320, 135, 0xffffff)  # 清空整个屏幕
    # [问题2修正] 更新 Widgets 以强制重绘，而不是调用.draw()
    last_input_label.setText(last_input_label.getText())
    current_mode_label.setText(current_mode_label.getText())
    input_label.setText(input_label.getText())
    # 手动绘制非 Widget 部分
    draw_output_text(output_string)


def translate():
    """翻译核心函数"""
    global input_string, last_morse_output, output_string

    # [新功能] 在翻译前，保存并显示本次的输入
    if input_string:
        last_input_label.setText(f"In: {input_string[:25]}")  # 限制长度防止溢出
    else:
        last_input_label.setText("")  # 如果没有输入，则清空

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
    draw_output_text(output_string)

    input_string = ""
    input_label.setText(">")


def play_morse():
    """播放莫斯电码声音，并同步屏幕闪烁"""
    global last_morse_output
    if not last_morse_output: return
    print("Playing morse with sound and light:", last_morse_output)
    for symbol in last_morse_output:
        duration = 0
        if symbol == '.':
            duration = 80
        elif symbol == '-':
            duration = 240
        if duration > 0:
            if speaker_on: Speaker.tone(800, duration)
            M5.Lcd.fillScreen(0x000000)
            time.sleep_ms(duration)
            M5.Lcd.fillScreen(0xffffff)
            time.sleep_ms(80)
        elif symbol == ' ':
            time.sleep_ms(160)
    if speaker_on: Speaker.noTone()
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
            print(f"Key detected: {repr(key_string)}")

            # [核心架构变更] 模态输入处理
            if is_menu_active:
                action = options_menu.handle_key(key_string)
                if action == 'close':
                    is_menu_active = False
                    redraw_ui()
                elif action == "Switch Mode":
                    current_mode_index = (current_mode_index + 1) % len(MODES)
                    current_mode_label.setText(MODES[current_mode_index])
                    is_menu_active = False
                    redraw_ui()
                elif action == "Play Demo":
                    is_menu_active = False
                    redraw_ui()
                    play_morse()
                elif action == "Speaker":
                    speaker_on = not speaker_on
                    # 菜单会在下一帧自动重绘并显示新状态
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
                    input_label.setText(">" + input_string)
                    is_selecting_preset = False
                    redraw_ui()

            else:
                # --- 正常模式下的输入处理 ---
                if key_string == '\t':
                    is_menu_active = True
                    options_menu.show()
                elif key_string in ('enter', '\r'):
                    # 修复了焦点问题：现在Enter只负责提交翻译
                    translate()
                elif key_string == '\x08':  # 删除键
                    input_string = input_string[:-1]
                    input_label.setText(">" + input_string)
                else:  # 其他所有可打印字符
                    input_string += key_string
                    input_label.setText(">" + input_string)

    last_key_state = is_key_down


def loop():
    M5.update()
    handle_input()

    # [核心架构变更] 在主循环中绘制模态UI
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