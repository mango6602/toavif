#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AVIF 图片转换工具
支持拖拽文件、多线程处理、GPU/CPU编码
"""

import os
import sys
import subprocess
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD
import json
import shutil
import platform

# 可选导入，避免在某些环境下出错
try:
    import winshell
    HAS_WINSHELL = True
except ImportError:
    HAS_WINSHELL = False
    print("警告: winshell未安装，删除原图功能将不可用")

try:
    from win32com.shell import shell, shellcon
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    print("警告: pywin32未安装，某些功能可能受限")



def format_file_size(size_bytes):
    """格式化文件大小"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

def format_duration(seconds):
    """格式化时间"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m{secs:.0f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h{minutes}m"

def validate_file_path(file_path):
    """验证和清理文件路径"""
    if not file_path or not os.path.exists(file_path):
        return False, "文件不存在"
    
    # 检查文件是否可读
    try:
        with open(file_path, 'rb') as f:
            f.read(1)
        return True, "OK"
    except PermissionError:
        return False, "文件权限不足"
    except Exception as e:
        return False, f"文件访问错误: {str(e)}"

def get_image_resolution_fast(file_path, ffprobe_path=None, timeout=3):
    """使用FFprobe快速获取图片分辨率"""
    if ffprobe_path is None:
        # 尝试常见的ffprobe路径
        ffprobe_candidates = ['ffprobe', 'ffprobe.exe']
        for candidate in ffprobe_candidates:
            try:
                subprocess.run([candidate, '-version'], 
                             capture_output=True, check=True, 
                             encoding='utf-8', errors='ignore', timeout=1)
                ffprobe_path = candidate
                break
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                continue
        
        if ffprobe_path is None:
            return None, None
    
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return None, None
        
        # 使用ffprobe获取视频流信息，优化参数以提高速度
        cmd = [
            ffprobe_path, 
            '-v', 'error',  # 只显示错误信息
            '-select_streams', 'v:0',  # 只选择第一个视频流
            '-show_entries', 'stream=width,height',  # 只获取宽度和高度
            '-of', 'csv=p=0',  # 使用CSV格式输出，去掉标题
            file_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, 
                              encoding='utf-8', errors='ignore', timeout=timeout)
        
        if result.returncode == 0 and result.stdout.strip():
            # CSV格式输出: width,height
            try:
                width_str, height_str = result.stdout.strip().split(',')
                width = int(width_str) if width_str != 'N/A' else None
                height = int(height_str) if height_str != 'N/A' else None
                return width, height
            except (ValueError, IndexError):
                pass
        
        return None, None
        
    except subprocess.TimeoutExpired:
        print(f"分辨率检测超时: {os.path.basename(file_path)}")
        return None, None
    except Exception as e:
        print(f"获取分辨率失败: {e}")
        return None, None


class AVIFConverter:
    def __init__(self):
        self.root = TkinterDnD.Tk()
        self.root.title("AVIF 图片转换工具")
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        
        # 配置变量
        self.quality = tk.IntVar(value=25)
        self.speed = tk.IntVar(value=5)
        self.delete_original_after_compress = tk.BooleanVar(value=True)  # 改名：压缩后删除原图
        self.delete_to_recycle_bin = tk.BooleanVar(value=True)  # 新增：删除时是否放入回收站
        self.max_threads = tk.IntVar(value=8)
        self.resolution_threads = tk.IntVar(value=6)  # 分辨率检测线程数
        self.use_gpu = tk.BooleanVar(value=True)
        self.auto_scale = tk.BooleanVar(value=False)
        self.skip_larger = tk.BooleanVar(value=True)
        self.height_limit = tk.BooleanVar(value=True)
        
        # 状态变量
        self.is_converting = False
        self.should_stop = False  # 新增：停止转换标志
        self.conversion_queue = []
        self.success_count = 0
        self.failed_count = 0
        self.processed_count = 0  # 新增：已处理数量
        self.total_start_time = None
        
        # 分辨率检测缓存 {文件路径: (宽度, 高度, 修改时间)}
        self.resolution_cache = {}
        
        # 检查FFmpeg和FFprobe
        self.ffmpeg_path = self.find_ffmpeg()
        self.ffprobe_path = self.find_ffprobe()
        
        # FFprobe分辨率检测线程池，使用配置的线程数
        self.ffprobe_executor = None  # 延迟初始化，等配置加载后设置
        self._current_thread_pool_size = None  # 跟踪当前线程池大小
        
        self.setup_ui()
        self.load_config()
        
    def find_ffmpeg(self):
        """查找FFmpeg路径"""
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, text=True, 
                                  encoding='utf-8', errors='ignore')
            if result.returncode == 0:
                return 'ffmpeg'
        except FileNotFoundError:
            pass
        
        # 检查常见路径
        common_paths = [
            'ffmpeg.exe',
            r'C:\ffmpeg\bin\ffmpeg.exe',
            r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
            './ffmpeg.exe'
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
                
        return None
    
    def find_ffprobe(self):
        """查找FFprobe路径"""
        try:
            result = subprocess.run(['ffprobe', '-version'], 
                                  capture_output=True, text=True, 
                                  encoding='utf-8', errors='ignore')
            if result.returncode == 0:
                return 'ffprobe'
        except FileNotFoundError:
            pass
        
        # 检查常见路径
        common_paths = [
            'ffprobe.exe',
            r'C:\ffmpeg\bin\ffprobe.exe',
            r'C:\Program Files\ffmpeg\bin\ffprobe.exe',
            './ffprobe.exe'
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
                
        return None
    
    def setup_ui(self):
        """设置用户界面"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # 标题
        title_label = ttk.Label(main_frame, text="AVIF 图片转换工具", 
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # FFmpeg状态
        ffmpeg_status = "✓ FFmpeg 已找到" if self.ffmpeg_path else "✗ 未找到 FFmpeg"
        status_color = "green" if self.ffmpeg_path else "red"
        ffmpeg_label = ttk.Label(main_frame, text=ffmpeg_status, foreground=status_color)
        ffmpeg_label.grid(row=1, column=0, columnspan=3, pady=(0, 10))
        
        # 配置区域
        config_frame = ttk.LabelFrame(main_frame, text="转换配置", padding="10")
        config_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)
        
        # 质量设置
        ttk.Label(config_frame, text="质量级别 (0-63):").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        quality_scale = ttk.Scale(config_frame, from_=0, to=63, variable=self.quality, orient=tk.HORIZONTAL)
        quality_scale.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        self.quality_label = ttk.Label(config_frame, text="25")
        self.quality_label.grid(row=0, column=2)
        quality_scale.configure(command=self.update_quality_label)
        
        # 编码速度
        ttk.Label(config_frame, text="编码速度 (0-9):").grid(row=1, column=0, sticky=tk.W, padx=(0, 10))
        speed_scale = ttk.Scale(config_frame, from_=0, to=9, variable=self.speed, orient=tk.HORIZONTAL)
        speed_scale.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        self.speed_label = ttk.Label(config_frame, text="5")
        self.speed_label.grid(row=1, column=2)
        speed_scale.configure(command=self.update_speed_label)
        
        # 转换线程数
        ttk.Label(config_frame, text="转换线程数:").grid(row=2, column=0, sticky=tk.W, padx=(0, 10))
        thread_scale = ttk.Scale(config_frame, from_=1, to=8, variable=self.max_threads, orient=tk.HORIZONTAL)
        thread_scale.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        self.thread_label = ttk.Label(config_frame, text="8")
        self.thread_label.grid(row=2, column=2)
        thread_scale.configure(command=self.update_thread_label)
        
        # 分辨率检测线程数
        ttk.Label(config_frame, text="分辨率检测线程数:").grid(row=3, column=0, sticky=tk.W, padx=(0, 10))
        resolution_thread_scale = ttk.Scale(config_frame, from_=1, to=10, variable=self.resolution_threads, orient=tk.HORIZONTAL)
        resolution_thread_scale.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        self.resolution_thread_label = ttk.Label(config_frame, text="6")
        self.resolution_thread_label.grid(row=3, column=2)
        resolution_thread_scale.configure(command=self.update_resolution_thread_label)
        
        # 选项 - 第一行
        options_frame1 = ttk.Frame(config_frame)
        options_frame1.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(10, 0))
        
        ttk.Checkbutton(options_frame1, text="优先使用GPU编码", variable=self.use_gpu).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Checkbutton(options_frame1, text="压缩后删除原图", variable=self.delete_original_after_compress).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Checkbutton(options_frame1, text="删除时放入回收站", variable=self.delete_to_recycle_bin).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Checkbutton(options_frame1, text="压缩无效时保留原图", variable=self.skip_larger).pack(side=tk.LEFT)
        
        # 选项 - 第二行
        options_frame2 = ttk.Frame(config_frame)
        options_frame2.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(5, 0))
        
        ttk.Checkbutton(options_frame2, text="宽度>7680时自动缩放", variable=self.auto_scale).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Checkbutton(options_frame2, text="高度>6000时自动缩放", variable=self.height_limit).pack(side=tk.LEFT)
        
        # 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=3, pady=(0, 10))
        
        ttk.Button(button_frame, text="选择文件", command=self.select_files).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="选择文件夹", command=self.select_folder).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(button_frame, text="清空列表", command=self.clear_queue).pack(side=tk.LEFT)
        
        # 文件列表区域
        list_frame = ttk.LabelFrame(main_frame, text="待转换文件 (可拖拽文件到此列表)", padding="10")
        list_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        # 创建容器框架用于拖拽和空状态显示
        self.list_container = ttk.Frame(list_frame)
        self.list_container.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.list_container.columnconfigure(0, weight=1)
        self.list_container.rowconfigure(0, weight=1)
        
        # 空状态提示（当没有文件时显示）
        self.empty_label = ttk.Label(self.list_container, 
                                    text="暂无文件\n\n拖拽图片文件到此处\n或点击上方按钮添加文件", 
                                    font=('Arial', 12), 
                                    anchor="center",
                                    foreground="gray")
        self.empty_label.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=50)
        
        # 创建Treeview（初始隐藏）
        columns = ('文件名', '分辨率', '原大小', '新大小', '压缩率', '状态', '耗时')
        self.file_tree = ttk.Treeview(self.list_container, columns=columns, show='headings', height=10)
        
        # 设置列标题和宽度
        self.file_tree.heading('文件名', text='文件名')
        self.file_tree.heading('分辨率', text='分辨率')
        self.file_tree.heading('原大小', text='原大小')
        self.file_tree.heading('新大小', text='新大小')
        self.file_tree.heading('压缩率', text='压缩率')
        self.file_tree.heading('状态', text='状态')
        self.file_tree.heading('耗时', text='耗时')
        
        self.file_tree.column('文件名', width=200)
        self.file_tree.column('分辨率', width=100)
        self.file_tree.column('原大小', width=80)
        self.file_tree.column('新大小', width=80)
        self.file_tree.column('压缩率', width=80)
        self.file_tree.column('状态', width=100)
        self.file_tree.column('耗时', width=80)
        
        # 滚动条
        scrollbar = ttk.Scrollbar(self.list_container, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=scrollbar.set)
        
        # 绑定拖拽事件到列表容器和空状态标签
        self.list_container.drop_target_register(DND_FILES)
        self.list_container.dnd_bind('<<Drop>>', self.on_drop)
        self.empty_label.drop_target_register(DND_FILES)
        self.empty_label.dnd_bind('<<Drop>>', self.on_drop)
        self.file_tree.drop_target_register(DND_FILES)
        self.file_tree.dnd_bind('<<Drop>>', self.on_drop)
        
        # 绑定右键菜单和双击事件
        self.file_tree.bind("<Button-3>", self.show_context_menu)  # 右键
        self.file_tree.bind("<Double-1>", self.on_double_click)  # 双击
        
        # 创建右键菜单
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="打开文件", command=self.open_selected_file)
        self.context_menu.add_command(label="打开文件位置", command=self.open_file_location)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="文件属性", command=self.show_file_properties)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="移出列表", command=self.remove_selected_item)
        self.context_menu.add_command(label="清空列表", command=self.clear_queue)
        
        # 控制按钮
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=5, column=0, columnspan=3, pady=(0, 10))
        
        self.start_button = ttk.Button(control_frame, text="开始转换", command=self.start_conversion)
        self.start_button.pack(side=tk.LEFT, padx=(0, 10))
        
        self.stop_button = ttk.Button(control_frame, text="停止转换", command=self.stop_conversion, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(control_frame, text="保存配置", command=self.save_config).pack(side=tk.LEFT, padx=(0, 10))
        
        # 状态栏
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E))
        status_frame.columnconfigure(1, weight=1)
        
        self.status_label = ttk.Label(status_frame, text="就绪")
        self.status_label.grid(row=0, column=0, sticky=tk.W)
        
        self.progress_bar = ttk.Progressbar(status_frame, mode='determinate')
        self.progress_bar.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(10, 10))
        
        self.count_label = ttk.Label(status_frame, text="成功: 0 | 失败: 0")
        self.count_label.grid(row=0, column=2, sticky=tk.E)
        
        # 配置主窗口网格权重
        main_frame.rowconfigure(4, weight=1)
    
    def update_quality_label(self, value):
        self.quality_label.config(text=str(int(float(value))))
    
    def update_speed_label(self, value):
        self.speed_label.config(text=str(int(float(value))))
    
    def update_thread_label(self, value):
        self.thread_label.config(text=str(int(float(value))))
    
    def update_resolution_thread_label(self, value):
        """更新分辨率检测线程数标签"""
        new_value = int(float(value))
        self.resolution_thread_label.config(text=str(new_value))
        
        # 使用防抖机制，避免滑块滑动时频繁重建线程池
        if hasattr(self, '_thread_pool_update_timer'):
            self.root.after_cancel(self._thread_pool_update_timer)
        
        # 延迟500毫秒后更新线程池，避免滑动过程中频繁触发
        self._thread_pool_update_timer = self.root.after(500, lambda: self.update_resolution_thread_pool(new_value))
    
    def update_resolution_thread_pool(self, new_max_workers):
        """动态更新分辨率检测线程池"""
        try:
            # 检查是否真的需要更新
            if (hasattr(self, '_current_thread_pool_size') and 
                self._current_thread_pool_size == new_max_workers):
                return
            
            if self.ffprobe_executor is not None:
                # 关闭当前线程池
                old_executor = self.ffprobe_executor
                old_executor.shutdown(wait=False)
            
            # 创建新的线程池
            self.ffprobe_executor = ThreadPoolExecutor(max_workers=new_max_workers)
            self._current_thread_pool_size = new_max_workers
            print(f"分辨率检测线程池已更新为 {new_max_workers} 个线程")
        except Exception as e:
            print(f"更新分辨率检测线程池失败: {e}")
    
    def get_cached_resolution(self, file_path):
        """从缓存获取分辨率信息"""
        try:
            if file_path in self.resolution_cache:
                cached_width, cached_height, cached_mtime = self.resolution_cache[file_path]
                current_mtime = os.path.getmtime(file_path)
                
                # 检查文件是否被修改过
                if abs(current_mtime - cached_mtime) < 1:  # 允许1秒的误差
                    return cached_width, cached_height
                else:
                    # 文件被修改过，删除缓存
                    del self.resolution_cache[file_path]
        except (OSError, KeyError):
            pass
        
        return None, None
    
    def cache_resolution(self, file_path, width, height):
        """缓存分辨率信息"""
        try:
            mtime = os.path.getmtime(file_path)
            self.resolution_cache[file_path] = (width, height, mtime)
            
            # 限制缓存大小，避免内存过度使用
            if len(self.resolution_cache) > 1000:
                # 删除最旧的50个条目
                items = list(self.resolution_cache.items())
                items.sort(key=lambda x: x[1][2])  # 按修改时间排序
                for i in range(50):
                    del self.resolution_cache[items[i][0]]
        except OSError:
            pass
    
    def on_drop(self, event):
        """处理拖拽文件事件"""
        files = self.root.tk.splitlist(event.data)
        print(f"拖拽的文件: {files}")  # 调试信息
        
        # 处理拖拽的文件和文件夹
        all_files = []
        for item in files:
            if os.path.isfile(item):
                # 检查是否为图片文件
                ext = os.path.splitext(item)[1].lower()
                if ext in {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.gif'}:
                    all_files.append(item)
            elif os.path.isdir(item):
                # 如果是文件夹，递归查找图片文件
                image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.gif'}
                for ext in image_extensions:
                    all_files.extend(str(f) for f in Path(item).rglob(f"*{ext}"))
                    all_files.extend(str(f) for f in Path(item).rglob(f"*{ext.upper()}"))
        
        if all_files:
            self.add_files(all_files)
        else:
            messagebox.showinfo("提示", "未找到支持的图片文件")
    
    def select_files(self):
        """选择文件"""
        filetypes = [
            ("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp *.tiff *.gif"),
            ("所有文件", "*.*")
        ]
        files = filedialog.askopenfilenames(filetypes=filetypes)
        if files:
            self.add_files(files)
    
    def select_folder(self):
        """选择文件夹"""
        folder = filedialog.askdirectory()
        if folder:
            # 递归查找文件夹中的图片文件
            image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.gif'}
            files = []
            for ext in image_extensions:
                files.extend(str(f) for f in Path(folder).rglob(f"*{ext}"))
                files.extend(str(f) for f in Path(folder).rglob(f"*{ext.upper()}"))
            
            if files:
                self.add_files(files)
                messagebox.showinfo("提示", f"找到 {len(files)} 个图片文件")
            else:
                messagebox.showinfo("提示", "所选文件夹中没有找到图片文件")
    
    def add_files(self, files):
        """添加文件到转换队列"""
        added_count = 0
        existing_paths = [item['path'] for item in self.conversion_queue]
        
        for file_path in files:
            # 确保路径格式统一
            file_path = os.path.normpath(file_path)
            
            if os.path.isfile(file_path) and file_path not in existing_paths:
                # 检查文件扩展名
                ext = os.path.splitext(file_path)[1].lower()
                if ext in {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.gif'}:
                    # 获取原文件大小
                    original_size = os.path.getsize(file_path)
                    
                    file_info = {
                        'path': file_path,
                        'name': os.path.basename(file_path),
                        'original_size': original_size,
                        'new_size': 0,
                        'compression_ratio': '',
                        'status': '等待中',
                        'duration': '',
                        'start_time': None,
                        'width': None,
                        'height': None,
                        'resolution_checked': False
                    }
                    self.conversion_queue.append(file_info)
                    
                    # 添加到树形视图（初始不显示分辨率）
                    item_id = self.file_tree.insert('', 'end', values=(
                        file_info['name'], 
                        '检测中...',
                        format_file_size(original_size),
                        '-',
                        '-',
                        file_info['status'], 
                        '-'
                    ))
                    
                    # 使用线程池检测分辨率
                    if self.ffprobe_path:
                        self.ffprobe_executor.submit(
                            self.detect_resolution_background,
                            len(self.conversion_queue) - 1, file_path, item_id
                        )
                    else:
                        # 没有ffprobe时直接更新为未知
                        self.root.after(0, lambda idx=len(self.conversion_queue) - 1, iid=item_id: 
                                      self.update_resolution_display(idx, iid, None, None))
                    
                    added_count += 1
                    existing_paths.append(file_path)
        
        if added_count > 0:
            self.status_label.config(text=f"已添加 {added_count} 个文件")
            self.update_list_display()
            print(f"成功添加 {added_count} 个文件到队列")  # 调试信息
        else:
            print("没有添加任何文件")  # 调试信息
    
    def detect_resolution_background(self, file_index, file_path, item_id):
        """后台线程检测图片分辨率"""
        try:
            # 检查文件是否仍在队列中
            if file_index >= len(self.conversion_queue):
                return
            
            file_info = self.conversion_queue[file_index]
            if file_info.get('resolution_checked', False):
                return  # 已经检测过了
            
            # 检查缓存
            width, height = self.get_cached_resolution(file_path)
            if width is not None and height is not None:
                # 使用缓存的结果
                self.root.after(0, lambda: self.update_resolution_display(file_index, item_id, width, height))
                return
            
            # 检测分辨率
            width, height = get_image_resolution_fast(file_path, self.ffprobe_path)
            
            # 缓存结果
            self.cache_resolution(file_path, width, height)
            
            # 使用UI线程更新显示
            self.root.after(0, lambda: self.update_resolution_display(file_index, item_id, width, height))
        except Exception as e:
            print(f"分辨率检测出错 [{os.path.basename(file_path)}]: {e}")
            # 检测失败时也要更新显示
            self.root.after(0, lambda: self.update_resolution_display(file_index, item_id, None, None))
    
    def update_resolution_display(self, file_index, item_id, width, height):
        """更新分辨率显示"""
        try:
            if file_index < len(self.conversion_queue):
                file_info = self.conversion_queue[file_index]
                file_info['width'] = width
                file_info['height'] = height
                file_info['resolution_checked'] = True
                
                # 格式化分辨率显示
                resolution_str = '-'
                if width and height:
                    resolution_str = f"{width}x{height}"
                
                # 更新树形视图中的分辨率列
                current_values = list(self.file_tree.item(item_id, 'values'))
                if len(current_values) >= 7:
                    current_values[1] = resolution_str  # 分辨率是第2列（索引1）
                    self.file_tree.item(item_id, values=current_values)
        except Exception as e:
            print(f"更新分辨率显示出错: {e}")
    
    def update_list_display(self):
        """更新列表显示状态"""
        if len(self.conversion_queue) > 0:
            # 有文件时显示列表，隐藏空状态提示
            self.empty_label.grid_remove()
            self.file_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            scrollbar = self.list_container.children.get('!scrollbar')
            if scrollbar:
                scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
            else:
                # 创建滚动条
                scrollbar = ttk.Scrollbar(self.list_container, orient=tk.VERTICAL, command=self.file_tree.yview)
                self.file_tree.configure(yscrollcommand=scrollbar.set)
                scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        else:
            # 没有文件时显示空状态提示，隐藏列表
            self.file_tree.grid_remove()
            scrollbar = self.list_container.children.get('!scrollbar')
            if scrollbar:
                scrollbar.grid_remove()
            self.empty_label.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=50)
    
    def clear_queue(self):
        """清空转换队列"""
        if not self.is_converting:
            self.conversion_queue.clear()
            for item in self.file_tree.get_children():
                self.file_tree.delete(item)
            self.status_label.config(text="队列已清空")
            self.update_list_display()
        else:
            messagebox.showwarning("警告", "转换进行中，无法清空队列")
    
    def show_context_menu(self, event):
        """显示右键菜单"""
        # 检查是否点击在有效项目上
        item = self.file_tree.identify_row(event.y)
        if item:
            # 选中点击的项目
            self.file_tree.selection_set(item)
            self.file_tree.focus(item)
            # 显示菜单
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()
    
    def on_double_click(self, event):
        """双击事件处理"""
        item = self.file_tree.identify_row(event.y)
        if item:
            self.file_tree.selection_set(item)
            self.file_tree.focus(item)
            self.open_selected_file()
    
    def get_selected_file_info(self):
        """获取选中的文件信息"""
        selection = self.file_tree.selection()
        if not selection:
            return None
        
        # 获取选中项的索引
        item = selection[0]
        children = self.file_tree.get_children()
        index = children.index(item)
        
        if 0 <= index < len(self.conversion_queue):
            return self.conversion_queue[index], index
        return None
    
    def open_selected_file(self):
        """打开选中的文件"""
        file_info = self.get_selected_file_info()
        if not file_info:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        
        file_data, index = file_info
        file_path = file_data['path']
        
        # 如果转换已完成，优先打开转换后的文件
        if file_data['status'] in ['转换完成', '完成(已删除至回收站)', '完成(已永久删除)']:
            # 获取输出文件路径
            output_path = self.get_output_path(file_path)
            if os.path.exists(output_path):
                file_path = output_path
        
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(file_path)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", file_path])
            else:  # Linux
                subprocess.run(["xdg-open", file_path])
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件: {str(e)}")
    
    def open_file_location(self):
        """打开文件所在位置"""
        file_info = self.get_selected_file_info()
        if not file_info:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        
        file_data, index = file_info
        file_path = file_data['path']
        
        # 如果转换已完成，优先打开转换后文件的位置
        if file_data['status'] in ['转换完成', '完成(已删除至回收站)', '完成(已永久删除)']:
            # 获取输出文件路径
            output_path = self.get_output_path(file_path)
            if os.path.exists(output_path):
                file_path = output_path
        
        try:
            system = platform.system()
            if system == "Windows":
                # Windows下选中文件并打开资源管理器
                subprocess.run(['explorer', '/select,', file_path])
            elif system == "Darwin":  # macOS
                # macOS下选中文件并打开Finder
                subprocess.run(["open", "-R", file_path])
            else:  # Linux
                # Linux下打开文件所在目录
                dir_path = os.path.dirname(file_path)
                subprocess.run(["xdg-open", dir_path])
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件位置: {str(e)}")
    
    def show_file_properties(self):
        """显示文件属性"""
        file_info = self.get_selected_file_info()
        if not file_info:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        
        file_data, index = file_info
        file_path = file_data['path']
        
        if not os.path.exists(file_path):
            messagebox.showerror("错误", "文件不存在")
            return
        
        try:
            # 获取文件信息
            stat_info = os.stat(file_path)
            file_size = stat_info.st_size
            modify_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_info.st_mtime))
            create_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_info.st_ctime))
            
            # 创建属性对话框
            prop_window = tk.Toplevel(self.root)
            prop_window.title("文件属性")
            prop_window.geometry("400x300")
            prop_window.resizable(False, False)
            prop_window.transient(self.root)
            prop_window.grab_set()
            
            # 居中显示
            prop_window.geometry("+%d+%d" % (
                self.root.winfo_rootx() + 50,
                self.root.winfo_rooty() + 50
            ))
            
            # 文件信息框架
            info_frame = ttk.LabelFrame(prop_window, text="文件信息", padding=10)
            info_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # 显示文件信息
            ttk.Label(info_frame, text="文件名:").grid(row=0, column=0, sticky=tk.W, pady=2)
            ttk.Label(info_frame, text=os.path.basename(file_path)).grid(row=0, column=1, sticky=tk.W, padx=10, pady=2)
            
            ttk.Label(info_frame, text="路径:").grid(row=1, column=0, sticky=tk.W, pady=2)
            path_label = ttk.Label(info_frame, text=file_path, wraplength=250)
            path_label.grid(row=1, column=1, sticky=tk.W, padx=10, pady=2)
            
            ttk.Label(info_frame, text="大小:").grid(row=2, column=0, sticky=tk.W, pady=2)
            ttk.Label(info_frame, text=f"{format_file_size(file_size)} ({file_size:,} 字节)").grid(row=2, column=1, sticky=tk.W, padx=10, pady=2)
            
            ttk.Label(info_frame, text="修改时间:").grid(row=3, column=0, sticky=tk.W, pady=2)
            ttk.Label(info_frame, text=modify_time).grid(row=3, column=1, sticky=tk.W, padx=10, pady=2)
            
            ttk.Label(info_frame, text="创建时间:").grid(row=4, column=0, sticky=tk.W, pady=2)
            ttk.Label(info_frame, text=create_time).grid(row=4, column=1, sticky=tk.W, padx=10, pady=2)
            
            # 如果有分辨率信息，显示分辨率
            if file_data.get('width') and file_data.get('height'):
                ttk.Label(info_frame, text="分辨率:").grid(row=5, column=0, sticky=tk.W, pady=2)
                ttk.Label(info_frame, text=f"{file_data['width']} × {file_data['height']}").grid(row=5, column=1, sticky=tk.W, padx=10, pady=2)
            
            # 转换信息
            if file_data['status'] != '等待中':
                ttk.Separator(info_frame, orient=tk.HORIZONTAL).grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
                
                ttk.Label(info_frame, text="转换状态:").grid(row=7, column=0, sticky=tk.W, pady=2)
                ttk.Label(info_frame, text=file_data['status']).grid(row=7, column=1, sticky=tk.W, padx=10, pady=2)
                
                if file_data['new_size'] > 0:
                    ttk.Label(info_frame, text="转换后大小:").grid(row=8, column=0, sticky=tk.W, pady=2)
                    ttk.Label(info_frame, text=format_file_size(file_data['new_size'])).grid(row=8, column=1, sticky=tk.W, padx=10, pady=2)
                
                if file_data['compression_ratio']:
                    ttk.Label(info_frame, text="压缩率:").grid(row=9, column=0, sticky=tk.W, pady=2)
                    ttk.Label(info_frame, text=file_data['compression_ratio']).grid(row=9, column=1, sticky=tk.W, padx=10, pady=2)
                
                if file_data['duration']:
                    ttk.Label(info_frame, text="转换耗时:").grid(row=10, column=0, sticky=tk.W, pady=2)
                    ttk.Label(info_frame, text=file_data['duration']).grid(row=10, column=1, sticky=tk.W, padx=10, pady=2)
            
            # 关闭按钮
            ttk.Button(prop_window, text="关闭", command=prop_window.destroy).pack(pady=10)
            
        except Exception as e:
            messagebox.showerror("错误", f"无法获取文件属性: {str(e)}")
    
    def remove_selected_item(self):
        """移出选中的项目"""
        if self.is_converting:
            messagebox.showwarning("警告", "转换进行中，无法移除文件")
            return
        
        file_info = self.get_selected_file_info()
        if not file_info:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        
        file_data, index = file_info
        
        # 确认删除
        result = messagebox.askyesno("确认", f"确定要从列表中移除 \"{file_data['name']}\" 吗？")
        if result:
            # 从队列中移除
            del self.conversion_queue[index]
            
            # 从树形视图中移除
            items = self.file_tree.get_children()
            if index < len(items):
                self.file_tree.delete(items[index])
            
            self.status_label.config(text=f"已移除: {file_data['name']}")
            self.update_list_display()
    
    def get_output_path(self, input_path):
        """获取输出文件路径"""
        # 根据配置生成输出路径
        directory = os.path.dirname(input_path)
        name_without_ext = os.path.splitext(os.path.basename(input_path))[0]
        
        if self.overwrite_var.get():
            # 覆盖原文件模式
            return os.path.join(directory, f"{name_without_ext}.avif")
        else:
            # 保存到指定目录
            output_dir = self.output_dir.get().strip()
            if not output_dir:
                output_dir = directory
            elif not os.path.isabs(output_dir):
                output_dir = os.path.join(directory, output_dir)
            
            # 确保输出目录存在
            os.makedirs(output_dir, exist_ok=True)
            return os.path.join(output_dir, f"{name_without_ext}.avif")
    
    def start_conversion(self):
        """开始转换"""
        if not self.ffmpeg_path:
            messagebox.showerror("错误", "未找到 FFmpeg，请确保已安装并添加到 PATH")
            return
        
        if not self.conversion_queue:
            messagebox.showwarning("警告", "没有要转换的文件")
            return
        
        if self.is_converting:
            return
        
        self.is_converting = True
        self.should_stop = False # 重置停止标志
        self.success_count = 0
        self.failed_count = 0
        self.processed_count = 0 # 重置已处理数量
        self.total_start_time = time.time()
        
        # 重置未完成文件的状态，跳过已完成的文件
        for i, file_info in enumerate(self.conversion_queue):
            current_status = file_info.get('status', '')
            # 如果文件已经成功完成，不重置状态
            if current_status not in ['转换完成', '完成(已删除至回收站)', '完成(已永久删除)', '跳过(压缩无效)']:
                file_info['status'] = '等待中'
                file_info['duration'] = ''
                file_info['start_time'] = None
                file_info['new_size'] = 0
                file_info['compression_ratio'] = ''
        
        # 更新UI状态
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.progress_bar.config(maximum=len(self.conversion_queue), value=0)
        self.status_label.config(text="转换中...")
        
        # 启动转换线程
        threading.Thread(target=self.run_conversion, daemon=True).start()
    
    def stop_conversion(self):
        """停止转换"""
        self.should_stop = True
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_label.config(text="转换已停止")
    
    def run_conversion(self):
        """运行转换任务"""
        max_workers = self.max_threads.get()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_index = {}
            for i, file_info in enumerate(self.conversion_queue):
                if self.should_stop: # 检查停止标志
                    break
                future = executor.submit(self.convert_file, file_info, i)
                future_to_index[future] = i
            
            # 处理完成的任务
            for future in as_completed(future_to_index):
                if self.should_stop: # 检查停止标志
                    break
                
                index = future_to_index[future]
                try:
                    success = future.result()
                    if success:
                        self.success_count += 1
                    else:
                        self.failed_count += 1
                except Exception as e:
                    print(f"转换出错: {e}")
                    self.failed_count += 1
                
                # 更新进度
                self.root.after(0, self.update_progress)
        
        # 转换完成
        self.root.after(0, self.conversion_complete)
    
    def convert_file(self, file_info, index):
        """转换单个文件"""
        # 检查是否应该停止
        if self.should_stop:
            return False
            
        # 检查文件是否已经完成过转换
        if file_info.get('status') == '转换完成' or file_info.get('status') == '完成(已删除)' or file_info.get('status') == '跳过(压缩无效)':
            print(f"跳过已完成的文件: {file_info['name']}")
            return True  # 标记为成功以便计数
        
        input_path = file_info['path']
        output_path = str(Path(input_path).with_suffix('.avif'))
        
        # 确保路径格式正确，处理特殊字符
        input_path = os.path.normpath(input_path)
        output_path = os.path.normpath(output_path)
        
        print(f"开始转换文件: {input_path}")
        print(f"输出路径: {output_path}")
        
        # 验证输入文件
        is_valid, error_msg = validate_file_path(input_path)
        if not is_valid:
            self.root.after(0, lambda: self.update_file_status(index, f"文件错误: {error_msg}"))
            return False
        
        # 记录开始时间
        start_time = time.time()
        file_info['start_time'] = start_time
        
        # 更新状态
        self.root.after(0, lambda: self.update_file_status(index, "转换中"))
        
        try:
            # 再次检查是否应该停止
            if self.should_stop:
                return False
                
            # 检查输出目录是否存在，如果不存在则创建
            output_dir = os.path.dirname(output_path)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            # 使用用户选择的编码方式
            use_gpu = self.use_gpu.get()
            
            # 构建FFmpeg命令，使用列表形式确保参数正确传递
            cmd = [self.ffmpeg_path, '-i', input_path, '-y']
            
            # 检查是否需要缩放
            need_scale = False
            scale_filter = None
            
            if file_info.get('width') and file_info.get('height'):
                width = file_info['width']
                height = file_info['height']
                new_width = width
                new_height = height
                
                # 检查宽度>7680的缩放
                if self.auto_scale.get() and new_width > 7680:
                    scale_ratio = 7680 / new_width
                    new_width = 7680
                    new_height = int(new_height * scale_ratio)
                    need_scale = True
                    print(f"宽度缩放: {width}x{height} -> {new_width}x{new_height}")
                
                # 检查高度>6000的缩放
                if self.height_limit.get() and new_height > 6000:
                    scale_ratio = 6000 / new_height
                    new_width = int(new_width * scale_ratio)
                    new_height = 6000
                    need_scale = True
                    print(f"高度限制缩放: {width}x{height} -> {new_width}x{new_height}")
                
                if need_scale:
                    # 确保尺寸为偶数（编码器要求）
                    new_width = new_width - (new_width % 2)
                    new_height = new_height - (new_height % 2)
                    
                    print(f"最终缩放: {width}x{height} -> {new_width}x{new_height}")
                    self.root.after(0, lambda: self.update_file_status(index, f"缩放中({new_width}x{new_height})"))
                    
                    # 添加缩放滤镜
                    cmd.extend(['-vf', f'scale={new_width}:{new_height}'])
            
            if use_gpu:
                # GPU编码 - 简化稳定参数
                cmd.extend([
                    '-c:v', 'av1_nvenc',
                    '-cq', str(self.quality.get()),
                    '-pix_fmt', 'yuv420p',
                    '-preset', 'p6'
                ])
            else:
                # CPU编码 - 优化参数配置
                cmd.extend([
                    '-c:v', 'libaom-av1',
                    '-crf', str(self.quality.get()),
                    '-cpu-used', str(self.speed.get()),
                    '-pix_fmt', 'yuv420p',
                    '-g', '1'                    # 全关键帧，适合静态图像
                ])
            
            cmd.append(output_path)
            
            # 调试信息：打印命令
            print(f"执行命令: {' '.join(repr(arg) for arg in cmd)}")
            print(f"输入文件存在: {os.path.exists(input_path)}")
            print(f"输入文件大小: {os.path.getsize(input_path) if os.path.exists(input_path) else 'N/A'}")
            
            # 执行转换，修复编码问题
            process = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            
            # 如果GPU编码失败，输出错误信息
            if process.returncode != 0:
                print(f"FFmpeg错误输出: {process.stderr}")
                print(f"FFmpeg标准输出: {process.stdout}")
            
            if process.returncode != 0 and use_gpu:
                # GPU失败，尝试CPU
                self.root.after(0, lambda: self.update_file_status(index, "GPU失败,尝试CPU"))
                
                cmd_cpu = [
                    self.ffmpeg_path, '-i', input_path, '-y', 
                    '-c:v', 'libaom-av1', 
                    '-crf', str(self.quality.get()), 
                    '-cpu-used', str(self.speed.get()), 
                    '-pix_fmt', 'yuv420p', 
                    output_path
                ]
                
                # 调试信息：打印CPU回退命令
                print(f"CPU回退命令: {' '.join(repr(arg) for arg in cmd_cpu)}")
                
                process = subprocess.run(cmd_cpu, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                
                # 输出CPU回退的错误信息
                if process.returncode != 0:
                    print(f"CPU回退也失败，错误输出: {process.stderr}")
                    print(f"CPU回退标准输出: {process.stdout}")
            
            if process.returncode == 0:
                # 计算转换时间
                end_time = time.time()
                duration = end_time - start_time
                file_info['duration'] = format_duration(duration)
                
                # 获取输出文件大小并计算压缩率
                if os.path.exists(output_path):
                    new_size = os.path.getsize(output_path)
                    original_size = file_info['original_size']
                    file_info['new_size'] = new_size
                    
                    if original_size > 0:
                        compression_ratio = (1 - new_size / original_size) * 100
                        file_info['compression_ratio'] = f"{compression_ratio:.1f}%"
                    
                    # 检查是否启用了"压缩无效时保留原图"选项
                    if self.skip_larger.get() and new_size >= original_size:
                        # 压缩后文件更大或相等，删除压缩文件，保留原图
                        try:
                            os.remove(output_path)
                            print(f"压缩无效，删除压缩文件: {format_file_size(new_size)} >= {format_file_size(original_size)}")
                            status = "跳过(压缩无效)"
                            file_info['compression_ratio'] = "无效"
                            self.root.after(0, lambda: self.update_file_status(index, status))
                            return True
                        except Exception as e:
                            print(f"删除压缩文件失败: {e}")
                            status = "完成(清理失败)"
                            self.root.after(0, lambda: self.update_file_status(index, status))
                            return True
                
                # 转换成功且压缩有效
                status = "转换完成"
                
                # 删除原图
                if self.delete_original_after_compress.get():
                    try:
                        if HAS_WINSHELL and self.delete_to_recycle_bin.get():
                            # 使用winshell移动到回收站
                            winshell.delete_file(input_path)
                            status = "完成(已删除至回收站)"
                        else:
                            # 直接删除文件（不放入回收站）
                            os.remove(input_path)
                            status = "完成(已永久删除)"
                    except Exception as e:
                        print(f"删除文件失败: {e}")
                        status = "完成(删除失败)"
                
                self.root.after(0, lambda: self.update_file_status(index, status))
                return True
            else:
                # 转换失败
                end_time = time.time()
                duration = end_time - start_time
                file_info['duration'] = format_duration(duration)
                self.root.after(0, lambda: self.update_file_status(index, "转换失败"))
                return False
                
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            file_info['duration'] = format_duration(duration)
            self.root.after(0, lambda: self.update_file_status(index, f"错误: {str(e)[:20]}"))
            return False
    
    def update_file_status(self, index, status):
        """更新文件状态"""
        try:
            items = self.file_tree.get_children()
            if index < len(items) and index < len(self.conversion_queue):
                item = items[index]
                file_info = self.conversion_queue[index]
                
                # 更新显示值
                new_size_str = format_file_size(file_info['new_size']) if file_info['new_size'] > 0 else '-'
                compression_str = file_info['compression_ratio'] if file_info['compression_ratio'] else '-'
                duration_str = file_info['duration'] if file_info['duration'] else '-'
                
                # 格式化分辨率显示
                resolution_str = '-'
                if file_info.get('width') and file_info.get('height'):
                    resolution_str = f"{file_info['width']}x{file_info['height']}"
                
                values = (
                    file_info['name'],
                    resolution_str,
                    format_file_size(file_info['original_size']),
                    new_size_str,
                    compression_str,
                    status,
                    duration_str
                )
                self.file_tree.item(item, values=values)
        except Exception as e:
            print(f"更新状态出错: {e}")
    
    def update_progress(self):
        """更新总进度"""
        completed = self.success_count + self.failed_count
        total = len(self.conversion_queue)
        self.progress_bar.config(value=completed)
        
        # 计算已用时间
        elapsed_time = 0
        if self.total_start_time:
            elapsed_time = time.time() - self.total_start_time
        elapsed_str = format_duration(elapsed_time)
        
        # 更新显示：已处理数/总处理数/已用时间
        progress_text = f"{completed}/{total} | 用时: {elapsed_str} | 成功: {self.success_count} | 失败: {self.failed_count}"
        self.count_label.config(text=progress_text)
    
    def conversion_complete(self):
        """转换完成"""
        self.is_converting = False
        self.should_stop = False  # 重置停止标志
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        
        # 计算总耗时
        total_duration = time.time() - self.total_start_time if self.total_start_time else 0
        total_duration_str = format_duration(total_duration)
        
        # 计算总体压缩统计
        total_original_size = sum(item['original_size'] for item in self.conversion_queue)
        total_new_size = sum(item['new_size'] for item in self.conversion_queue if item['new_size'] > 0)
        overall_compression = 0
        if total_original_size > 0 and total_new_size > 0:
            overall_compression = (1 - total_new_size / total_original_size) * 100
        
        total = len(self.conversion_queue)
        status_text = f"转换完成 - 总计: {total}, 成功: {self.success_count}, 失败: {self.failed_count}, 总耗时: {total_duration_str}"
        self.status_label.config(text=status_text)
        
        # 显示完成消息
        message = f"转换完成！\n\n总计: {total} 个文件\n成功: {self.success_count} 个\n失败: {self.failed_count} 个\n总耗时: {total_duration_str}"
        if overall_compression > 0:
            message += f"\n总体压缩率: {overall_compression:.1f}%"
            message += f"\n原始大小: {format_file_size(total_original_size)}"
            message += f"\n压缩后: {format_file_size(total_new_size)}"
        
        messagebox.showinfo("转换完成", message)
    
    def save_config(self):
        """保存配置"""
        config = {
            'quality': self.quality.get(),
            'speed': self.speed.get(),
            'delete_original_after_compress': self.delete_original_after_compress.get(),
            'delete_to_recycle_bin': self.delete_to_recycle_bin.get(),
            'max_threads': self.max_threads.get(),
            'resolution_threads': self.resolution_threads.get(),
            'use_gpu': self.use_gpu.get(),
            'auto_scale': self.auto_scale.get(),
            'skip_larger': self.skip_larger.get(),
            'height_limit': self.height_limit.get()
        }
        
        try:
            with open('avif_config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("提示", "配置已保存")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")
    
    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists('avif_config.json'):
                with open('avif_config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                self.quality.set(config.get('quality', 25))
                self.speed.set(config.get('speed', 5))
                self.delete_original_after_compress.set(config.get('delete_original_after_compress', True))
                self.delete_to_recycle_bin.set(config.get('delete_to_recycle_bin', True))
                self.max_threads.set(config.get('max_threads', 8))
                resolution_threads = config.get('resolution_threads', 6)
                self.resolution_threads.set(resolution_threads)
                self.use_gpu.set(config.get('use_gpu', True))
                self.auto_scale.set(config.get('auto_scale', False))
                self.skip_larger.set(config.get('skip_larger', True))
                self.height_limit.set(config.get('height_limit', True))
                
                # 初始化分辨率检测线程池
                if self.ffprobe_executor is None:
                    self.ffprobe_executor = ThreadPoolExecutor(max_workers=resolution_threads)
                    self._current_thread_pool_size = resolution_threads
                
                # 更新标签
                self.quality_label.config(text=str(self.quality.get()))
                self.speed_label.config(text=str(self.speed.get()))
                self.thread_label.config(text=str(self.max_threads.get()))
                self.resolution_thread_label.config(text=str(self.resolution_threads.get()))
        except Exception as e:
            print(f"加载配置失败: {e}")
        
        # 确保分辨率检测线程池被初始化
        if self.ffprobe_executor is None:
            self.ffprobe_executor = ThreadPoolExecutor(max_workers=6)  # 默认6个线程
            self._current_thread_pool_size = 6
    
    def run(self):
        """运行应用程序"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()
    
    def on_closing(self):
        """关闭程序时的处理"""
        if self.is_converting:
            if messagebox.askokcancel("退出", "转换正在进行中，确定要退出吗？"):
                self.is_converting = False
                self.cleanup_and_exit()
        else:
            self.cleanup_and_exit()
    
    def cleanup_and_exit(self):
        """清理资源并退出"""
        try:
            # 关闭FFprobe线程池
            if self.ffprobe_executor is not None:
                self.ffprobe_executor.shutdown(wait=False)
        except:
            pass
        self.root.destroy()


def main():
    """主函数入口"""
    app = AVIFConverter()
    app.run()

if __name__ == "__main__":
    main() 