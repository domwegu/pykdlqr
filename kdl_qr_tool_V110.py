# Create a complete Python file with the latest requested behavior.
# Features:
# - Tkinter GUI with Fallnummer field and KDL dropdown (loaded from kdl_embedded.json or fallback)
# - QR generation in format {sys:GUN_CID,cid:<Fallnummer>,formid:<KDL-Code>}
# - Printing to the default Windows printer
# - Label width 4 cm, QR size max 2.5 cm (square), text (Fallnummer, KDL display) to the right of QR, print date at bottom
# - Command-line parameter FALL to prefill Fallnummer
# - Simple favorites using usage file in %APPDATA%\KDL_QR_Tool\kdl_usage.json

code = r'''import os
import sys
import json
import tkinter as tk
from tkinter import ttk, messagebox

import qrcode
from PIL import Image, ImageTk, ImageWin, ImageDraw, ImageFont

import win32print
import win32ui
import win32con

# ---------------------------
# Embedded fallback KDL data
# ---------------------------
FALLBACK_KDL_DATA = [
    {"code": "A01", "display": "Cholera durch Vibrio cholerae 01, Biovar cholerae"},
    {"code": "A02", "display": "Salmonellenenteritis"},
    {"code": "B20", "display": "HIV-Krankheit, durch HIV-1-Virus"},
    {"code": "C34", "display": "Bösartige Neubildung: Bronchien und Lunge"},
    {"code": "E11", "display": "Nicht insulinabhängiger Diabetes mellitus"},
    {"code": "I10", "display": "Essentielle (primäre) Hypertonie"},
    {"code": "J45", "display": "Asthma bronchiale"},
    {"code": "K35", "display": "Akute Appendizitis"},
    {"code": "M54", "display": "Rückenschmerzen"},
    {"code": "N39", "display": "Sonstige Krankheiten der Harnorgane"},
]

# ---------------------------
# Robust KDL loader
# ---------------------------
def load_kdl_data():
    """
    Try to load kdl_embedded.json from typical locations:
    - next to the EXE (PyInstaller onefile)
    - current working directory
    - next to the .py file
    Fallback to embedded list if not found/invalid.
    """
    fname = "kdl_embedded.json"
    candidates = []
    try:
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            candidates.append(os.path.join(exe_dir, fname))
        candidates.append(os.path.join(os.getcwd(), fname))
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(here, fname))
    except Exception:
        pass

    for path in candidates:
        try:
            if path and os.path.exists(path):
                # robust encoding handling
                with open(path, "rb") as f:
                    raw = f.read()
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("cp1252")
                data = json.loads(text)
                if isinstance(data, list) and all(isinstance(x, dict) and "code" in x and "display" in x for x in data):
                    return data
        except Exception:
            continue

    return FALLBACK_KDL_DATA

KDL_DATA = load_kdl_data()

# ---------------------------
# Favorites storage
# ---------------------------
APP_DIR = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "KDL_QR_Tool")
os.makedirs(APP_DIR, exist_ok=True)
USAGE_FILE = os.path.join(APP_DIR, "kdl_usage.json")

def load_usage():
    try:
        if os.path.exists(USAGE_FILE):
            with open(USAGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_usage(data):
    try:
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

usage_data = load_usage()

# ---------------------------
# App
# ---------------------------
class KDLQRApp:
    def __init__(self, root, fallnummer_param=None):
        self.root = root
        self.root.title("KDL QR Tool")

        # UI
        tk.Label(root, text="Fallnummer:").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        self.fallnummer_entry = tk.Entry(root)
        self.fallnummer_entry.grid(row=0, column=1, padx=6, pady=6, sticky="ew")
        if fallnummer_param:
            self.fallnummer_entry.insert(0, fallnummer_param)

        tk.Label(root, text="KDL:").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        self.kdl_var = tk.StringVar()
        self.kdl_dropdown = ttk.Combobox(root, textvariable=self.kdl_var, state="readonly", width=60)
        self.update_dropdown()
        self.kdl_dropdown.grid(row=1, column=1, padx=6, pady=6, sticky="ew")

        self.qr_label = tk.Label(root)
        self.qr_label.grid(row=2, column=0, padx=6, pady=6, sticky="nw")

        btn_frame = tk.Frame(root)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10)
        tk.Button(btn_frame, text="QR-Code erstellen", command=self.generate_qr).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Drucken", command=self.print_qr).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Favoriten zurücksetzen", command=self.reset_favorites).pack(side="left", padx=6)

        root.grid_columnconfigure(1, weight=1)

        self.qr_pil = None
        self.qr_img = None

    # ----- Favorites & Dropdown -----
    def update_dropdown(self):
        # Top-5 favorites based on usage_data
        valid_usage = {code: usage_data.get(code, 0) for code in (e["code"] for e in KDL_DATA)}
        favorites_sorted = sorted(valid_usage.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        favorite_codes = [code for code, _ in favorites_sorted if usage_data.get(code, 0) > 0]
        favorite_displays = [e["display"] for e in KDL_DATA if e["code"] in favorite_codes]

        remaining_displays = [e["display"] for e in sorted(KDL_DATA, key=lambda x: x["display"]) if e["display"] not in favorite_displays]

        values = []
        if favorite_displays:
            values.extend(favorite_displays)
            values.append("---")
        values.extend(remaining_displays)
        self.kdl_dropdown["values"] = values

    def get_kdl_code(self, display):
        for entry in KDL_DATA:
            if entry["display"] == display:
                return entry["code"]
        return None

    # ----- QR generation -----
    def generate_qr(self):
        fallnummer = self.fallnummer_entry.get().strip()
        display = self.kdl_var.get().strip()
        if not display or display == "---":
            messagebox.showerror("Fehler", "Bitte einen KDL-Eintrag wählen.")
            return
        code = self.get_kdl_code(display)
        if not fallnummer or not code:
            messagebox.showerror("Fehler", "Bitte Fallnummer und KDL auswählen.")
            return

        qr_data = f"{{sys:GUN_CID,cid:{fallnummer},formid:{code}}}"
        self.qr_pil = qrcode.make(qr_data)

        preview = self.qr_pil.resize((200, 200), Image.NEAREST)
        self.qr_img = ImageTk.PhotoImage(preview)
        self.qr_label.configure(image=self.qr_img)

        # update usage
        usage_data[code] = usage_data.get(code, 0) + 1
        save_usage(usage_data)
        self.update_dropdown()

    # ----- Printing -----
    def print_qr(self):
        if self.qr_pil is None:
            messagebox.showerror("Fehler", "Bitte zuerst einen QR-Code generieren.")
            return
        try:
            # Use default printer
            dev_name = win32print.GetDefaultPrinter()

            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(dev_name)

            hdc.StartDoc("KDL QR Label")
            hdc.StartPage()

            dpi_x = hdc.GetDeviceCaps(win32con.LOGPIXELSX)
            dpi_y = hdc.GetDeviceCaps(win32con.LOGPIXELSY)
            CM_TO_IN = 0.3937007874

            # QR: max 2.5 cm side
            qr_side_px = int(2.5 * CM_TO_IN * min(dpi_x, dpi_y))
            qr_print = self.qr_pil.resize((qr_side_px, qr_side_px), Image.NEAREST)

            # Label width 4 cm (height dynamic = qr height + bottom line)
            label_width_px = int(4 * CM_TO_IN * dpi_x)
            label_height_px = qr_side_px + int(0.4 * CM_TO_IN * dpi_y)  # some space for date

            final_img = Image.new("RGB", (label_width_px, label_height_px), "white")
            final_img.paste(qr_print, (0, 0))

            draw = ImageDraw.Draw(final_img)
            # pick a readable font
            try:
                font = ImageFont.truetype("arial.ttf", 14)
            except IOError:
                font = ImageFont.load_default()

            text_x = qr_side_px + int(0.2 * CM_TO_IN * dpi_x)
            fallnummer = self.fallnummer_entry.get().strip()
            kdl_display = self.kdl_var.get().strip()

            draw.text((text_x, 0), f"Fallnummer: {fallnummer}", fill="black", font=font)
            draw.text((text_x, int(0.7 * CM_TO_IN * dpi_y)), f"KDL: {kdl_display}", fill="black", font=font)

            from datetime import datetime
            druckdatum = datetime.now().strftime("%d.%m.%Y %H:%M")
            # bottom-left
            draw.text((0, qr_side_px), druckdatum, fill="black", font=font)

            # send to printer
            dib = ImageWin.Dib(final_img)
            dib.draw(hdc.GetHandleOutput(), (0, 0, label_width_px, label_height_px))

            hdc.EndPage()
            hdc.EndDoc()
            hdc.DeleteDC()
        except Exception as e:
            messagebox.showerror("Druckfehler", str(e))

    def reset_favorites(self):
        global usage_data
        usage_data = {}
        save_usage(usage_data)
        self.update_dropdown()
        messagebox.showinfo("Info", "Favoriten wurden zurückgesetzt.")

# ----- Entry point -----
if __name__ == "__main__":
    fall_arg = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        s = a.strip()
        low = s.lower()
        if low.startswith("fall="):
            fall_arg = s.split("=", 1)[1]
            break
        if low in ("--fall", "/fall", "-fall"):
            if i + 1 < len(args):
                fall_arg = args[i + 1]
            break

    root = tk.Tk()
    app = KDLQRApp(root, fallnummer_param=fall_arg)
    root.mainloop()
'''

path = "/mnt/data/KDL_QR_Tool_v106_plus_labeltext.py"
with open(path, "w", encoding="utf-8") as f:
    f.write(code)

path
