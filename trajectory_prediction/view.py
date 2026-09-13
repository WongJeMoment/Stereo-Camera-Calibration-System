"""Desktop viewer: python -m trajectory_prediction.view (Tk + OpenCV decoding)."""
import argparse
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parents[1]
VIEWS = {"三视角合成": "multiview", "左目": "Stereo_Left",
         "右目": "Stereo_Right", "侧面": "Side_Overview"}


class Player:
    def __init__(self, window, folder, speed=.25):
        self.window, self.folder = window, folder
        self.cap = None
        self.frame = 0
        self.playing = False
        self.speed = speed
        self.rgb = None
        self.photo = None
        self.timer = None
        window.title("物体轨迹预测 · 三相机查看器")
        window.geometry("1280x850")
        window.minsize(800, 550)
        window.protocol("WM_DELETE_WINDOW", self.close)
        toolbar = ttk.Frame(window, padding=8)
        toolbar.pack(fill="x")
        self.selected = tk.StringVar(value="三视角合成")
        combo = ttk.Combobox(toolbar, textvariable=self.selected, values=list(VIEWS), state="readonly", width=14)
        combo.pack(side="left", padx=5)
        combo.bind("<<ComboboxSelected>>", lambda _: self.switch())
        self.play_button = ttk.Button(toolbar, text="播放 / 空格", command=self.toggle)
        self.play_button.pack(side="left", padx=5)
        ttk.Button(toolbar, text="上一帧 ←", command=lambda: self.step(-1)).pack(side="left", padx=5)
        ttk.Button(toolbar, text="下一帧 →", command=lambda: self.step(1)).pack(side="left", padx=5)
        self.rate = tk.StringVar(value=str(speed))
        rate = ttk.Combobox(toolbar, textvariable=self.rate, values=("0.1", "0.25", "0.5", "1.0"), state="readonly", width=6)
        rate.pack(side="left", padx=5)
        rate.bind("<<ComboboxSelected>>", lambda _: self.change_speed())
        ttk.Label(toolbar, text="倍速").pack(side="left")
        self.canvas = tk.Canvas(window, background="#101a29", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.image_item = self.canvas.create_image(0, 0, anchor="center")
        self.canvas.bind("<Configure>", lambda _: self.draw())
        bottom = ttk.Frame(window, padding=8)
        bottom.pack(fill="x")
        self.position = tk.DoubleVar(value=0)
        self.slider = ttk.Scale(bottom, from_=0, to=59, variable=self.position, command=self.seek)
        self.slider.pack(fill="x")
        self.status = ttk.Label(bottom)
        self.status.pack(anchor="w")
        ttk.Label(bottom, text="青色：真实轨迹   橙色：预测轨迹   XYZ：世界坐标（米）   总误差：厘米\n"
                  "空格：播放/暂停   ←/→：逐帧   0：合成  1：左目  2：右目  3：侧面   Esc：退出").pack(anchor="w")
        window.bind("<space>", lambda _: self.toggle())
        window.bind("<Left>", lambda _: self.step(-1))
        window.bind("<Right>", lambda _: self.step(1))
        window.bind("<Escape>", lambda _: self.close())
        for key, name in zip("0123", VIEWS):
            window.bind(key, lambda _, n=name: self.select(n))
        self.switch()
        self.timer = window.after(10, self.tick)

    def select(self, name):
        self.selected.set(name)
        self.switch()

    def switch(self):
        path = self.folder / (VIEWS[self.selected.get()] + ".mp4")
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"无法读取视频：{path}")
        if self.cap is not None:
            self.cap.release()
        self.cap = cap
        self.total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = cap.get(cv2.CAP_PROP_FPS)
        if self.total <= 0 or self.fps <= 0:
            raise RuntimeError(f"视频帧数或帧率无效：{path}")
        self.slider.configure(to=self.total-1)
        self.show(min(self.frame, self.total-1))
        self.reset_clock()

    def reset_clock(self):
        self.anchor_frame = self.frame
        self.anchor_time = time.monotonic()

    def show(self, frame):
        frame = max(0, min(self.total-1, frame))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, image = self.cap.read()
        if not ok:
            raise RuntimeError(f"无法解码第 {frame+1} 帧")
        self.frame = frame
        self.rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        self.position.set(frame)
        self.status.configure(text=f"第 {frame+1} / {self.total} 帧   视频时间 {frame/self.fps:.3f} s   "
                              f"原始 {image.shape[1]}×{image.shape[0]} / {self.fps:g} FPS")
        self.draw()

    def draw(self):
        if self.rgb is None:
            return
        w, h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        image = self.rgb.copy()
        image.thumbnail((w, h), Image.Resampling.BILINEAR)
        self.photo = ImageTk.PhotoImage(image)
        self.canvas.itemconfigure(self.image_item, image=self.photo)
        self.canvas.coords(self.image_item, w/2, h/2)

    def pause(self):
        self.playing = False
        self.play_button.configure(text="播放 / 空格")

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.playing = True
            self.play_button.configure(text="暂停 / 空格")
            self.reset_clock()
        return "break"

    def step(self, delta):
        self.pause()
        self.show(self.frame+delta)
        return "break"

    def seek(self, value):
        self.pause()
        frame = int(round(float(value)))
        if frame != self.frame:
            self.show(frame)

    def change_speed(self):
        self.speed = float(self.rate.get())
        self.reset_clock()

    def tick(self):
        if self.playing:
            frame = (self.anchor_frame + int((time.monotonic()-self.anchor_time)*self.fps*self.speed)) % self.total
            if frame != self.frame:
                self.show(frame)
        self.timer = self.window.after(10, self.tick)

    def close(self):
        if self.timer is not None:
            self.window.after_cancel(self.timer)
            self.timer = None
        if self.cap is not None:
            self.cap.release()
        self.window.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=ROOT / "results/trajectory_prediction/views/gravity")
    parser.add_argument("--check", action="store_true", help="Open, decode each view and close to check the desktop viewer")
    args = parser.parse_args()
    missing = [n+".mp4" for n in VIEWS.values() if not (args.folder / (n+".mp4")).is_file()]
    if missing:
        parser.error("缺少视频：" + ", ".join(missing) + "；请先运行 python -m trajectory_prediction.render_views")
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        parser.exit(1, f"无法打开桌面窗口，请在图形桌面的终端运行：{exc}\n")
    player = None
    try:
        player = Player(window, args.folder)
        if args.check:
            window.update()
            for name in VIEWS:
                player.select(name)
                player.show(player.total-1)
                window.update()
                assert player.frame == player.total-1
            player.step(-1)
            player.seek("5")
            assert player.frame == 5
            print("Desktop viewer checked: 4 views, frame seeking and rendering OK")
            player.close()
        else:
            window.mainloop()
    finally:
        if player is not None and player.cap is not None:
            player.cap.release()


if __name__ == "__main__":
    main()
