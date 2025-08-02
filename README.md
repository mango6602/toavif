# AVIF 图片转换工具

一个基于Python的图形界面AVIF图片转换工具，支持拖拽操作、多线程处理和GPU/CPU编码。

## 功能特点

- 🖼️ **多格式支持**: 支持JPG、PNG、WEBP、BMP、TIFF、GIF等常见图片格式转换为AVIF
- 🖱️ **拖拽操作**: 支持直接拖拽文件或文件夹到程序界面
- ⚡ **多线程处理**: 支持并发处理多个文件，提高转换效率
- 🚀 **GPU加速**: 优先使用NVIDIA GPU编码（av1_nvenc），GPU失败时自动回退到CPU编码
- ⚙️ **灵活配置**: 可调节质量级别、编码速度、线程数等参数
- 📊 **实时进度**: 显示每个文件的转换状态和总体进度
- 🗑️ **智能清理**: 可选择将原图移至回收站
- 💾 **配置保存**: 自动保存和加载用户配置

## 系统要求

- Windows 10/11
- Python 3.7+
- FFmpeg (需要支持av1_nvenc和libaom-av1编码器)
- NVIDIA显卡 (可选，用于GPU加速)

## 安装说明

### 1. 安装Python依赖

```bash
pip install -r requirements.txt
```

### 2. 安装FFmpeg

#### 方法一：下载预编译版本
1. 访问 [FFmpeg官网](https://ffmpeg.org/download.html#build-windows)
2. 下载Windows版本的FFmpeg
3. 解压到任意目录（如 `C:\ffmpeg`）
4. 将FFmpeg的bin目录添加到系统PATH环境变量

#### 方法二：使用包管理器
```bash
# 使用Chocolatey
choco install ffmpeg

# 使用Scoop
scoop install ffmpeg
```

### 3. 验证安装

运行以下命令验证FFmpeg是否正确安装：
```bash
ffmpeg -version
```

## 使用方法

### 启动程序
```bash
python avif_converter.py
```

### 操作步骤

1. **配置参数**
   - 质量级别：0-63，值越小质量越高（推荐15-35）
   - 编码速度：0-9，0质量最好但最慢，9速度最快但质量较低
   - 并发线程数：根据CPU核心数调整（推荐2-8）
   - GPU编码：勾选后优先使用GPU编码
   - 删除原图：勾选后转换成功的原图将移至回收站

2. **添加文件**
   - 拖拽文件到程序界面
   - 点击"选择文件"按钮
   - 点击"选择文件夹"按钮批量添加

3. **开始转换**
   - 点击"开始转换"按钮
   - 程序将显示每个文件的转换进度
   - 可随时点击"停止转换"中断处理

4. **查看结果**
   - 转换完成后会显示成功和失败的文件数量
   - AVIF文件将保存在原文件相同目录

## 配置文件

程序会自动保存配置到 `avif_config.json` 文件，包含以下设置：

```json
{
  "quality": 25,
  "speed": 5,
  "delete_original": true,
  "max_threads": 4,
  "use_gpu": true
}
```

## 编码器说明

### GPU编码 (av1_nvenc)
- **优点**: 速度快，CPU占用低
- **缺点**: 需要NVIDIA RTX 40系列或更新的显卡
- **参数**: 使用CQ模式控制质量

### CPU编码 (libaom-av1)
- **优点**: 兼容性好，质量优秀
- **缺点**: 速度较慢，CPU占用高
- **参数**: 使用CRF模式控制质量，cpu-used控制速度

## 性能优化建议

1. **GPU编码**: 如有支持的NVIDIA显卡，优先使用GPU编码
2. **线程数**: 设置为CPU核心数的50-100%
3. **质量设置**: 
   - 高质量: 15-25
   - 平衡: 25-35
   - 高压缩: 35-45
4. **批量处理**: 一次添加多个文件可提高效率

## 故障排除

### FFmpeg未找到
- 确保FFmpeg已正确安装并添加到PATH
- 或将ffmpeg.exe放在程序同目录下

### GPU编码失败
- 确认显卡支持AV1编码（RTX 40系列及以上）
- 更新显卡驱动到最新版本
- 程序会自动回退到CPU编码

### 转换失败
- 检查输入文件是否损坏
- 确认有足够的磁盘空间
- 查看FFmpeg错误信息

### 程序卡顿
- 减少并发线程数
- 关闭其他占用资源的程序
- 使用GPU编码减少CPU负载

## 技术细节

- **界面框架**: Tkinter + tkinterdnd2
- **多线程**: concurrent.futures.ThreadPoolExecutor
- **文件操作**: winshell (回收站功能)
- **进程调用**: subprocess (FFmpeg)
- **配置管理**: JSON格式

## 许可证

本项目基于Apache-2.0许可证开源。

## 更新日志

### v1.0.0
- 初始版本发布
- 支持基本的AVIF转换功能
- GUI界面和拖拽操作
- 多线程处理
- GPU/CPU编码支持 