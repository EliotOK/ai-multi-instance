"""Warm paper-like account hub, with a responsive canvas and native tray lifecycle."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, font as tkfont

from manager_backend import Account, ManagerService, Snapshot
from windows_shell import DesktopShell, ICON, TITLE
from app_paths import data_root
from ui_fonts import PrivateFonts
from account_display import validate_display

BG = "#17140F"
CARD = "#27221C"
TEXT = "#F2E7D1"
MUTED = "#B9AA92"
ACCENT = "#DCAA35"
ROSE = "#D583A5"
SKY = "#64AFCB"
SHADOW = "#090705"
INACTIVE = "#766B5A"


class HubWindow:
    def __init__(self, root, service=None, app_key="codex", native=True, shell_identity=None):
        self.root = root
        self.service = service or ManagerService()
        self.app_key = app_key
        self.accounts = {}
        self.selected_key = None
        self.selected_by_app = {}
        self.busy = False
        self.refresh_pending = False
        self.closed = False
        self.requests = queue.Queue()
        self.responses = queue.Queue()
        self.last_message = "正在读取账号状态…"
        self.regions = []
        self.shell = None
        self.drain_timer = None
        self.tick_timer = None
        self.record_diagnostics = service is None
        self.fonts = PrivateFonts(root)
        self.hover_key = None
        self.card_regions = []
        self.editor = None
        self.create_dialog = None
        self.card_height = 82
        self.card_step = 94
        self.scale = max(1, root.winfo_fpixels("1i") / 96)
        root.title(TITLE)
        width = min(int(940 * self.scale), root.winfo_screenwidth() - 80)
        height = min(int(680 * self.scale), root.winfo_screenheight() - 110)
        root.geometry(f"{width}x{height}+{max(0,(root.winfo_screenwidth()-width)//2)}+{max(0,(root.winfo_screenheight()-height)//2)}")
        root.minsize(int(760 * self.scale), int(620 * self.scale))
        root.configure(bg=BG)
        root.iconbitmap(str(ICON))
        self.canvas = tk.Canvas(root, bg=BG, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self.draw())
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Motion>", self.hover)
        self.canvas.bind("<Leave>", lambda event: self.clear_hover())
        self.cards = tk.Canvas(root, bg=BG, bd=0, highlightthickness=0)
        self.cards.bind("<Button-1>", self.select_card)
        self.cards.bind("<Double-Button-1>", lambda event: self.edit_account(self.selected_key))
        self.cards.bind("<Motion>", self.hover_card)
        self.cards.bind("<MouseWheel>", lambda event: self.cards.yview_scroll(-int(event.delta / 120), "units"))
        root.protocol("WM_DELETE_WINDOW", self.hide)
        root.bind("<F5>", lambda event: self.refresh(manual=True))
        root.bind("<Return>", lambda event: self.act("open"))
        root.bind("<Up>", lambda event: self.move_selection(-1))
        root.bind("<Down>", lambda event: self.move_selection(1))
        root.bind("<F2>", lambda event: self.edit_account(self.selected_key))
        if native:
            try:
                self.shell = DesktopShell(root, identity_suffix=shell_identity)
            except (OSError, AttributeError) as exc:
                self.last_message = "托盘启动失败：" + str(exc)
        self.worker = threading.Thread(target=self._worker,
            args=(self.requests,self.responses,self.service,self.record_diagnostics),daemon=True)
        self.worker.start()
        self.drain_timer = root.after(100, self._drain)
        self.tick_timer = root.after(3000, self._tick)
        self.refresh()
        self.draw()
        self.diagnostics()

    def font(self, size, bold=False, display=False):
        family = self.fonts.display if display else self.fonts.rounded if bold else "Microsoft YaHei UI"
        return (family, -round(size * self.scale), "normal")

    def text(self, canvas, x, y, text, size=14, color=TEXT, bold=False, anchor="w", display=False, **kwargs):
        display = display or (bold and str(text).isascii())
        return canvas.create_text(x*self.scale, y*self.scale, text=text, font=self.font(size,bold,display),
                                  fill=color, anchor=anchor, **kwargs)

    def rounded(self, canvas, x, y, width, height, fill, outline=None, radius=14, stroke=1.5):
        s = self.scale
        r = min(radius, height/2, width/2)
        points = [x+r,y,x+width-r,y,x+width,y,x+width,y+r,x+width,y+height-r,
                  x+width,y+height,x+width-r,y+height,x+r,y+height,x,y+height,
                  x,y+height-r,x,y+r,x,y]
        return canvas.create_polygon(*[p*s for p in points], smooth=True, splinesteps=24,
            fill=fill, outline=outline or fill, width=max(1,stroke*s))

    def panel(self, canvas, x, y, width, height, fill=CARD, border=TEXT, radius=14, shadow=4, stroke=1.5):
        self.rounded(canvas,x+shadow,y+shadow,width,height,SHADOW,radius=radius)
        return self.rounded(canvas,x,y,width,height,fill,border,radius,stroke)

    def button(self, key, x, y, width, label, kind="secondary", enabled=True):
        colors = {"primary": (ACCENT, BG), "secondary": (CARD, TEXT),
                  "danger": (CARD, ROSE), "quiet": (BG, MUTED)}
        fill, ink = colors[kind]
        if not enabled:
            fill, ink = "#211D17", INACTIVE
        elif key == self.hover_key:
            fill = "#E4B844" if kind=="primary" else "#393025"
        self.panel(self.canvas,x,y,width,46,fill,TEXT if enabled else "#544936",radius=23,shadow=3)
        self.text(self.canvas,x+width/2,y+23,label,14,ink,True,"center")
        if enabled:
            self.regions.append((x,y,x+width,y+46,key))

    def draw(self):
        if self.closed:
            return
        c = self.canvas
        c.delete("all")
        self.regions = []
        width = max(760,c.winfo_width()/self.scale)
        height = max(620,c.winfo_height()/self.scale)
        # Geometric mark: two overlapping windows, matching the .ico artwork.
        self.panel(c,32,29,50,50,CARD,TEXT,radius=25,shadow=3)
        self.rounded(c,42,41,23,19,ACCENT,TEXT,radius=5)
        self.rounded(c,51,49,23,19,SKY,TEXT,radius=5)
        c.create_line(54*self.scale,55*self.scale,71*self.scale,55*self.scale,fill=BG,width=1.2*self.scale)
        self.text(c,98,48,"Instance Hub",32,TEXT,True)
        self.text(c,98,79,"AI 账号启动器 · 多账号，统一管理",13,MUTED)
        self.text(c,width-32,49,"本机 / 桌面",12,MUTED,anchor="e")
        online = sum(a.running is True for a in self.accounts.values())
        self.rounded(c,32,114,214,40,CARD,TEXT,radius=20)
        for index,(key,label) in enumerate((("codex","Codex"),("claude","Claude"))):
            x=34+index*106
            selected=key==self.app_key
            if selected:
                self.rounded(c,x,116,104,36,ACCENT,radius=18)
            self.text(c,x+52,134,label,18,BG if selected else MUTED,True,"center")
            if not self.busy:
                self.regions.append((x,116,x+104,152,"app:"+key))
        self.button("refresh",width-133,110,101,"刷新","quiet",not self.busy)
        # A small dotted status sheet, using the reference site's warm palette.
        self.panel(c,32,177,width-68,124)
        for x in range(48,int(width)-54,18):
            for y in range(191,289,18):
                c.create_oval(x*self.scale,y*self.scale,(x+1.5)*self.scale,(y+1.5)*self.scale,fill="#40372B",outline="")
        self.text(c,54,203,"当前运行",12,MUTED)
        self.rounded(c,53,221,115,55,ACCENT,radius=9)
        self.text(c,69,250,f"{online:02d}",41,BG,True,display=True)
        self.text(c,130,253,"个",16,BG,True)
        self.text(c,192,237,"账号独立登录",20,TEXT,True)
        self.text(c,192,267,"在这里启动、显示、重启或退出账号。",13,MUTED)
        unknown=sum(a.running is None for a in self.accounts.values())
        status = "等待读取" if not self.accounts else "状态待确认" if unknown else "已连接"
        self.rounded(c,width-147,226,92,32,SKY if not unknown else ROSE,radius=16)
        self.text(c,width-101,242,status,12,BG,True,"center")
        self.text(c,32,331,"你的账号",21,TEXT,True)
        self.text(c,width-260,332,f"{len(self.accounts):02d} 个账号",12,MUTED,anchor="e")
        self.button("create",width-240,305,204,"添加账号" if self.app_key=="codex" else "Claude 暂不可用",
                    "secondary",not self.busy and self.app_key=="codex")
        card_height=max(86,height-480)
        self.cards.place(x=round(31*self.scale),y=round(354*self.scale),width=round((width-61)*self.scale),height=round(card_height*self.scale))
        self.draw_cards(width-64)
        selected=self.selected()
        active=selected is not None and selected.running is not None and not self.busy
        self.button("open",32,height-114,194,"显示窗口" if selected and selected.running else "启动账号","primary",active)
        self.button("restart",239,height-114,120,"重启账号","secondary",active)
        self.button("close",372,height-114,120,"退出账号","danger",active and selected.running)
        login_enabled = not self.busy and self.app_key=="codex" and selected is not None and selected.name is not None
        self.button("login",505,height-114,140,"登录账号" if self.app_key=="codex" else "Claude 登录暂不可用",
                    "secondary",login_enabled)
        self.text(c,32,height-41,self.last_message,12,ACCENT if self.busy else MUTED,
                  width=round((width-64)*self.scale))
        hint="点击托盘图标恢复窗口 · 右键托盘退出启动器" if self.shell and self.shell.added else "关闭启动器后，账号仍继续运行"
        self.text(c,32,height-19,hint,11,INACTIVE)

    def draw_cards(self,width):
        c=self.cards
        c.delete("all")
        self.card_regions=[]
        if not self.accounts:
            self.text(c,20,45,"正在发现账号…",14,MUTED)
        for index,account in enumerate(self.accounts.values()):
            y=index*self.card_step+2
            selected=account.key==self.selected_key
            self.panel(c,2,y,width-10,self.card_height,"#32291D" if selected else CARD,
                       ACCENT if selected else "#7D705C",radius=14,stroke=2 if selected else 1.3)
            self.rounded(c,20,y+17,46,46,ACCENT if selected else ROSE if index%2==0 else SKY,radius=10)
            self.text(c,43,y+40,f"{index+1:02d}",24,BG,True,"center",display=True)
            label = self.fit_text(account.label,19,width-326,bold=True)
            self.text(c,85,y+27,label,19,TEXT,True)
            detail = self.fit_text(account.detail,12,width-326)
            self.text(c,85,y+55,detail,12,MUTED)
            if account.running is True:
                status,fill,ink="运行中",SKY,BG
            elif account.running is False:
                status,fill,ink="未启动",CARD,MUTED
            else:
                status,fill,ink="状态未知",ROSE,BG
            self.rounded(c,width-216,y+25,105,32,fill,ink if account.running is False else fill,radius=16,stroke=1)
            self.text(c,width-164,y+41,status,12,ink,True,anchor="center")
            self.rounded(c,width-97,y+25,66,32,CARD,"#7D705C",radius=16,stroke=1)
            self.text(c,width-64,y+41,"编辑",12,MUTED if not self.busy else INACTIVE,True,anchor="center")
            if not self.busy:
                self.card_regions.append((width-97,y+25,width-31,y+57,account.key))
        c.configure(scrollregion=(0,0,width*self.scale,max(94,len(self.accounts)*self.card_step)*self.scale))

    def fit_text(self,value,size,width,bold=False):
        measure=tkfont.Font(root=self.root,font=self.font(size,bold)).measure
        if measure(value)<=width*self.scale:
            return value
        while value and measure(value+"…")>width*self.scale:
            value=value[:-1]
        return value+"…"

    def hover(self,event):
        x,y=event.x/self.scale,event.y/self.scale
        key=next((r[-1] for r in self.regions if r[0]<=x<=r[2] and r[1]<=y<=r[3]),None)
        self.canvas.configure(cursor="hand2" if key else "")
        if key!=self.hover_key:
            self.hover_key=key
            self.draw()

    def clear_hover(self):
        self.hover_key=None
        self.canvas.configure(cursor="")
        self.draw()

    def click(self,event):
        x,y=event.x/self.scale,event.y/self.scale
        for left,top,right,bottom,key in self.regions:
            if left<=x<=right and top<=y<=bottom:
                if key.startswith("app:"):
                    self.change_app(key.split(":",1)[1])
                elif key=="refresh":
                    self.refresh(manual=True)
                elif key=="create":
                    self.create_account()
                else:
                    self.act(key)
                return

    def select_card(self,event):
        if self.busy:
            return
        x,y=event.x/self.scale,self.cards.canvasy(event.y)/self.scale
        for left,top,right,bottom,key in self.card_regions:
            if left<=x<=right and top<=y<=bottom:
                self.selected_key=key
                self.edit_account(key)
                return
        index=int(self.cards.canvasy(event.y)/self.scale//self.card_step)
        if self.cards.canvasy(event.y)/self.scale%self.card_step > self.card_height+2:
            return
        keys=list(self.accounts)
        if 0<=index<len(keys):
            self.selected_key=keys[index]
            self.draw()

    def hover_card(self,event):
        x,y=event.x/self.scale,self.cards.canvasy(event.y)/self.scale
        self.cards.configure(cursor="hand2" if any(l<=x<=r and t<=y<=b for l,t,r,b,key in self.card_regions) else "")

    def edit_account(self,key):
        if self.busy or key not in self.accounts:
            return
        if self.editor and self.editor.winfo_exists():
            self.editor.lift()
            return
        self.selected_key=key
        self.draw()
        account=self.accounts[key]
        dialog=tk.Toplevel(self.root)
        self.editor=dialog
        self.editor_key=key
        dialog.title("编辑账号")
        dialog.transient(self.root)
        dialog.configure(bg=CARD)
        dialog.resizable(False,False)
        dialog.iconbitmap(str(ICON))
        pad=round(24*self.scale)
        frame=tk.Frame(dialog,bg=CARD)
        frame.pack(fill="both",expand=True,padx=pad,pady=pad)
        tk.Label(frame,text="给账号起个名字",bg=CARD,fg=TEXT,font=self.font(22,True),anchor="w").pack(fill="x")
        tk.Label(frame,text="名称和描述会保存在启动器中。",bg=CARD,fg=MUTED,font=self.font(12),anchor="w").pack(fill="x",pady=(4,12))
        self.editor_name=tk.StringVar(value=account.label)
        self.editor_description=tk.StringVar(value=account.detail)
        self.editor_status=tk.StringVar()
        for title,variable in (("名称",self.editor_name),("描述",self.editor_description)):
            tk.Label(frame,text=title,bg=CARD,fg=MUTED,font=self.font(12),anchor="w").pack(fill="x",pady=(8,5))
            entry=tk.Entry(frame,textvariable=variable,width=34,font=self.font(15),bg=BG,fg=TEXT,
                           insertbackground=TEXT,relief="flat",highlightthickness=1,highlightbackground="#7D705C",highlightcolor=ACCENT)
            entry.pack(fill="x",ipady=round(8*self.scale))
            if title=="名称":
                self.editor_name_entry=entry
        tk.Label(frame,textvariable=self.editor_status,bg=CARD,fg=ROSE,font=self.font(12),anchor="w").pack(fill="x",pady=(10,8))
        buttons=tk.Frame(frame,bg=CARD)
        buttons.pack(fill="x")
        tk.Button(buttons,text="取消",command=self.close_editor,bg=CARD,fg=TEXT,activebackground=BG,activeforeground=TEXT,
                  relief="flat",font=self.font(14,True),padx=22,pady=6).pack(side="right")
        self.editor_save=tk.Button(buttons,text="保存",command=self.save_editor,bg=ACCENT,fg=BG,activebackground="#E4B844",
                                   activeforeground=BG,relief="flat",font=self.font(14,True),padx=22,pady=6)
        self.editor_save.pack(side="right",padx=(0,10))
        dialog.protocol("WM_DELETE_WINDOW",self.close_editor)
        dialog.bind("<Escape>",lambda event:self.close_editor())
        dialog.bind("<Return>",lambda event:self.save_editor())
        dialog.update_idletasks()
        x=self.root.winfo_rootx()+max(0,(self.root.winfo_width()-dialog.winfo_width())//2)
        y=self.root.winfo_rooty()+max(0,(self.root.winfo_height()-dialog.winfo_height())//2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        self.editor_name_entry.focus_set()
        self.editor_name_entry.selection_range(0,"end")

    def close_editor(self):
        if self.editor and self.editor.winfo_exists():
            self.editor.grab_release()
            self.editor.destroy()
        self.editor=None

    def create_account(self):
        if self.busy or self.app_key != "codex":
            if self.app_key == "claude":
                self.last_message="Claude 新账号登录暂不可用。"
                self.draw()
            return
        if self.create_dialog and self.create_dialog.winfo_exists():
            self.create_dialog.lift()
            return
        dialog=tk.Toplevel(self.root)
        self.create_dialog=dialog
        dialog.title("添加 Codex 账号")
        dialog.transient(self.root)
        dialog.configure(bg=CARD)
        dialog.resizable(False,False)
        dialog.iconbitmap(str(ICON))
        pad=round(24*self.scale)
        frame=tk.Frame(dialog,bg=CARD)
        frame.pack(fill="both",expand=True,padx=pad,pady=pad)
        tk.Label(frame,text="添加独立 Codex 账号",bg=CARD,fg=TEXT,font=self.font(22,True),anchor="w").pack(fill="x")
        tk.Label(frame,text="将创建新的本机资料目录，不会读取或复制主账号登录信息。",
                 bg=CARD,fg=MUTED,font=self.font(12),anchor="w",wraplength=430).pack(fill="x",pady=(4,8))
        tk.Label(frame,text="首次启动后，请在 Codex 官方窗口中登录；浏览器登录会返回该窗口。",
                 bg=CARD,fg=MUTED,font=self.font(12),anchor="w",wraplength=430).pack(fill="x",pady=(0,8))
        self.create_name=tk.StringVar()
        self.create_description=tk.StringVar()
        self.create_status=tk.StringVar()
        for title,variable in (("名称",self.create_name),("描述（可选）",self.create_description)):
            tk.Label(frame,text=title,bg=CARD,fg=MUTED,font=self.font(12),anchor="w").pack(fill="x",pady=(8,5))
            entry=tk.Entry(frame,textvariable=variable,width=36,font=self.font(15),bg=BG,fg=TEXT,
                           insertbackground=TEXT,relief="flat",highlightthickness=1,highlightbackground="#7D705C",highlightcolor=ACCENT)
            entry.pack(fill="x",ipady=round(8*self.scale))
            if title=="名称":
                self.create_name_entry=entry
        tk.Label(frame,textvariable=self.create_status,bg=CARD,fg=ROSE,font=self.font(12),anchor="w",wraplength=430).pack(fill="x",pady=(10,8))
        buttons=tk.Frame(frame,bg=CARD)
        buttons.pack(fill="x")
        self.create_cancel=tk.Button(buttons,text="取消",command=self.close_create_dialog,bg=CARD,fg=TEXT,activebackground=BG,
                                     activeforeground=TEXT,relief="flat",font=self.font(14,True),padx=22,pady=6)
        self.create_cancel.pack(side="right")
        self.create_submit=tk.Button(buttons,text="创建并打开",command=self.submit_create_account,bg=ACCENT,fg=BG,
                                     activebackground="#E4B844",activeforeground=BG,relief="flat",
                                     font=self.font(14,True),padx=22,pady=6)
        self.create_submit.pack(side="right",padx=(0,10))
        dialog.protocol("WM_DELETE_WINDOW",lambda:self.close_create_dialog())
        dialog.bind("<Escape>",lambda event:self.close_create_dialog())
        dialog.bind("<Return>",lambda event:self.submit_create_account())
        dialog.update_idletasks()
        x=self.root.winfo_rootx()+max(0,(self.root.winfo_width()-dialog.winfo_width())//2)
        y=self.root.winfo_rooty()+max(0,(self.root.winfo_height()-dialog.winfo_height())//2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        self.create_name_entry.focus_set()

    def close_create_dialog(self,force=False):
        if self.busy and not force:
            return
        if self.create_dialog and self.create_dialog.winfo_exists():
            self.create_dialog.grab_release()
            self.create_dialog.destroy()
        self.create_dialog=None

    def submit_create_account(self):
        if self.busy or not self.create_dialog:
            return
        try:
            values=validate_display(self.create_name.get(),self.create_description.get())
        except ValueError as exc:
            self.create_status.set(str(exc))
            return
        self.busy=True
        self.create_status.set("正在创建独立账号并打开 Codex…")
        self.create_submit.configure(state="disabled")
        self.create_cancel.configure(state="disabled")
        self.draw()
        self.requests.put(("create","codex",None,values))

    def save_editor(self):
        if self.busy or not self.editor:
            return
        try:
            values=validate_display(self.editor_name.get(),self.editor_description.get())
        except ValueError as exc:
            self.editor_status.set(str(exc))
            return
        account=self.accounts[self.editor_key]
        self.editor_values=values
        self.busy=True
        self.editor_status.set("正在保存…")
        self.editor_save.configure(state="disabled")
        self.requests.put(("edit",self.app_key,account.name,values))
        self.draw()

    def move_selection(self,delta):
        keys=list(self.accounts)
        if not keys or self.busy:
            return
        index=keys.index(self.selected_key) if self.selected_key in keys else 0
        self.selected_key=keys[max(0,min(len(keys)-1,index+delta))]
        self.cards.yview_moveto(max(0,(index+delta)*self.card_step/(len(keys)*self.card_step)))
        self.draw()

    def selected(self):
        return self.accounts.get(self.selected_key)

    def render(self,snapshot):
        self.accounts={a.key:a for a in snapshot.accounts}
        if self.selected_key not in self.accounts:
            self.selected_key=next((a.key for a in snapshot.accounts if a.name is not None),"main")
        if snapshot.error:
            self.last_message=snapshot.error
        elif self.last_message in ("正在读取账号状态…","正在刷新…"):
            self.last_message="选择账号，打开或管理它的窗口。"
        self.draw()

    def change_app(self,key):
        if self.busy or key==self.app_key:
            return
        self.selected_by_app[self.app_key]=self.selected_key
        self.app_key=key
        self.selected_key=self.selected_by_app.get(key)
        self.accounts={}
        self.last_message="正在读取账号状态…"
        self.cards.yview_moveto(0)
        self.draw()
        self.refresh()

    def refresh(self,manual=False):
        if self.closed or self.busy or self.refresh_pending:
            return
        if manual:
            self.last_message="正在刷新…"
            self.draw()
        self.refresh_pending=True
        self.requests.put(("refresh",self.app_key,None,None))

    def act(self,action):
        account=self.selected()
        if self.busy or account is None:
            return
        if action == "login":
            if self.app_key != "codex" or account.name is None:
                return
            self.busy=True
            self.last_message=f"正在打开{account.label}的 Codex 官方客户端…"
            self.draw()
            self.requests.put(("login","codex",account.name,None))
            return
        if account.running is None:
            return
        if action=="close" and not account.running:
            return
        self.busy=True
        verb={"open":"打开","restart":"重启","close":"退出"}[action]
        self.last_message=f"正在{verb}{account.label}…"
        self.draw()
        self.requests.put(("action",self.app_key,account.name,action))

    @staticmethod
    def _worker(requests,responses,service,maintain_appearance):
        # Keep Tk objects out of the background thread, including on shutdown.
        while True:
            request=requests.get()
            if request is None:
                return
            kind,app,name,action=request
            try:
                if kind=="refresh":
                    result=service.snapshot(app)
                    if maintain_appearance:
                        service.maintain_appearance(result)
                elif kind=="edit":
                    result=service.save_display(app,name,*action)
                elif kind=="create":
                    result=service.create_codex_account(*action)
                elif kind=="login":
                    result=service.login_codex_profile(name)
                else:
                    result=service.perform(app,name,action)
                responses.put((kind,app,result,None))
            except Exception as exc:
                responses.put((kind,app,None,str(exc)))

    def _drain(self):
        if self.closed:
            return
        if self.shell:
            while True:
                try:
                    event=self.shell.events.get_nowait()
                except queue.Empty:
                    break
                if event=="show":
                    self.show()
                elif event=="quit":
                    self.close()
                    return
        while True:
            try:
                kind,app,result,error=self.responses.get_nowait()
            except queue.Empty:
                break
            if kind=="refresh":
                self.refresh_pending=False
                if app!=self.app_key:
                    self.refresh()
                    continue
                if error:
                    self.last_message="读取账号失败："+error
                    self.draw()
                else:
                    self.render(result)
            elif kind=="create":
                self.busy=False
                if error:
                    self.last_message="账号未创建"
                    if self.create_dialog:
                        self.create_status.set(error)
                        self.create_submit.configure(state="normal")
                        self.create_cancel.configure(state="normal")
                else:
                    name,message=result
                    self.selected_key="profile:"+name
                    self.close_create_dialog(force=True)
                    self.last_message=message
                self.draw()
                self.refresh()
            else:
                self.busy=False
                if kind=="edit":
                    if error:
                        if self.editor:
                            self.editor_status.set(error)
                            self.editor_save.configure(state="normal")
                    else:
                        if self.editor_key in self.accounts:
                            self.accounts[self.editor_key]=replace(self.accounts[self.editor_key],display_name=result[0],description=result[1])
                        self.close_editor()
                        self.last_message="账号名称和描述已保存。"
                    self.draw()
                    self.refresh()
                    continue
                if error:
                    self.last_message="操作未完成"
                    messagebox.showerror("操作未完成",error,parent=self.root)
                else:
                    self.last_message=result
                self.draw()
                self.refresh()
        self.drain_timer = self.root.after(100,self._drain)

    def _tick(self):
        if not self.closed:
            self.refresh()
            self.tick_timer = self.root.after(3000,self._tick)

    def hide(self):
        self.close_editor()
        self.close_create_dialog()
        if self.shell and self.shell.added:
            self.root.withdraw()
            self.diagnostics()
        else:
            self.close()

    def show(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        if self.shell:
            self.shell.api.foreground(self.shell.root_hwnd)
        self.refresh()
        self.diagnostics()

    def diagnostics(self):
        if self.shell and self.record_diagnostics:
            data=self.shell.diagnostics()
            data["window_state"]=self.root.state()
            data["data_root"]=str(data_root())
            data["theme"]="warm-paper"
            data["fonts"]={"display":self.fonts.display,"rounded":self.fonts.rounded}
            try:
                target=data_root()/"manager-runtime.json"
                target.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
            except OSError:
                pass

    def close(self):
        if self.closed:
            return
        self.closed=True
        for timer in (self.drain_timer,self.tick_timer):
            if timer:
                try:
                    self.root.after_cancel(timer)
                except tk.TclError:
                    pass
        self.requests.put(None)
        self.close_editor()
        self.close_create_dialog()
        if self.shell:
            self.shell.close()
        self.root.destroy()
        self.fonts.close()
