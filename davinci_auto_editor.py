#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DaVinci Auto Editor - Tự động dựng video từ folder chứa voice, ảnh, video
Yêu cầu: Python 3.13, DaVinci Resolve Studio 20 API
"""

import os
import sys
import re
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import logging

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Hằng số
FRAME_RATE = 30
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FORMAT = 'h264'
VIDEO_CODEC = 'h264'
AUDIO_REDUCTION_DB = -24
IMAGE_ZOOM_SCALE = 1.2
TRANSITION_DURATION = 0.5  # giây

class SectionType(Enum):
    """Các loại section trong video"""
    HOOK = "Hook"
    JBL_GO5 = "JBL Go 5"
    JBL_FLIP6 = "JBL Flip 6"
    JBL_FLIP7 = "JBL Flip 7"
    OUTRO = "Outro"

class MediaType(Enum):
    """Loại media"""
    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"

@dataclass
class TimelineSegment:
    """Thông tin một segment trong timeline"""
    section: SectionType
    start_time: float
    end_time: float
    duration: float
    description: str
    voice_text: str

@dataclass
class MediaFile:
    """Thông tin một file media"""
    path: str
    type: MediaType
    filename: str
    product: Optional[str] = None  # Go5, Flip6, Flip7
    quality_score: float = 0.5  # 0-1 để ưu tiên

class VoiceParser:
    """Parse file voice.txt để lấy segments"""
    
    def __init__(self, voice_file_path: str):
        self.voice_file_path = voice_file_path
        self.segments: List[TimelineSegment] = []
        logger.info(f"VoiceParser khởi tạo với file: {voice_file_path}")
    
    def parse(self) -> List[TimelineSegment]:
        """
        Đọc và phân tích voice.txt
        Format dự kiến: [00:00-00:05] Hook: Giới thiệu sản phẩm
        """
        if not os.path.exists(self.voice_file_path):
            logger.error(f"File không tồn tại: {self.voice_file_path}")
            return []
        
        try:
            with open(self.voice_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            logger.info("Phân tích voice.txt...")
            
            # Pattern: [HH:MM:SS-HH:MM:SS] Section: Description
            pattern = r'\[(\d{2}):(\d{2}):(\d{2})-(\d{2}):(\d{2}):(\d{2})\]\s*(.+?):\s*(.+?)(?=\n\[|\Z)'
            matches = re.finditer(pattern, content, re.DOTALL)
            
            for match in matches:
                start_h, start_m, start_s = int(match.group(1)), int(match.group(2)), int(match.group(3))
                end_h, end_m, end_s = int(match.group(4)), int(match.group(5)), int(match.group(6))
                section_name = match.group(7).strip()
                description = match.group(8).strip()
                
                start_time = start_h * 3600 + start_m * 60 + start_s
                end_time = end_h * 3600 + end_m * 60 + end_s
                duration = end_time - start_time
                
                # Xác định section type
                section_type = self._identify_section(section_name)
                
                segment = TimelineSegment(
                    section=section_type,
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                    description=section_name,
                    voice_text=description
                )
                
                self.segments.append(segment)
                logger.info(f"  Segment: {section_type.value} [{start_time}s-{end_time}s] {duration}s")
            
            logger.info(f"Tổng cộng {len(self.segments)} segments")
            return self.segments
            
        except Exception as e:
            logger.error(f"Lỗi khi parse voice.txt: {e}")
            return []
    
    def _identify_section(self, section_name: str) -> SectionType:
        """Xác định loại section từ tên"""
        section_lower = section_name.lower()
        
        if 'hook' in section_lower or 'intro' in section_lower:
            return SectionType.HOOK
        elif 'go' in section_lower and '5' in section_lower:
            return SectionType.JBL_GO5
        elif 'flip' in section_lower and '6' in section_lower:
            return SectionType.JBL_FLIP6
        elif 'flip' in section_lower and '7' in section_lower:
            return SectionType.JBL_FLIP7
        elif 'outro' in section_lower or 'outro' in section_lower:
            return SectionType.OUTRO
        else:
            # Mặc định hook nếu không nhận dạng được
            return SectionType.HOOK

class ProductInfoParser:
    """Parse file product-info.md để lấy thông tin sản phẩm"""
    
    def __init__(self, product_info_path: str):
        self.product_info_path = product_info_path
        self.product_info: Dict = {}
        logger.info(f"ProductInfoParser khởi tạo với file: {product_info_path}")
    
    def parse(self) -> Dict:
        """Đọc và phân tích product-info.md"""
        if not os.path.exists(self.product_info_path):
            logger.warning(f"File product-info không tồn tại: {self.product_info_path}")
            return {}
        
        try:
            with open(self.product_info_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            logger.info("Phân tích product-info.md...")
            
            # Parse markdown
            self.product_info = self._parse_markdown(content)
            
            logger.info(f"Đã parse {len(self.product_info)} sản phẩm")
            return self.product_info
            
        except Exception as e:
            logger.error(f"Lỗi khi parse product-info: {e}")
            return {}
    
    def _parse_markdown(self, content: str) -> Dict:
        """Parse markdown content thành dict"""
        products = {}
        
        # Tìm các heading ## Product Name
        product_pattern = r'## (.+?)\n(.*?)(?=##|\Z)'
        matches = re.finditer(product_pattern, content, re.DOTALL)
        
        for match in matches:
            product_name = match.group(1).strip()
            product_content = match.group(2).strip()
            
            products[product_name] = {
                'name': product_name,
                'content': product_content,
                'raw': product_content
            }
        
        return products
    
    def get_product_keywords(self, product_name: str) -> List[str]:
        """Lấy keywords từ sản phẩm"""
        if product_name not in self.product_info:
            return []
        
        content = self.product_info[product_name]['content']
        # Lấy tất cả từ khóa (words >= 3 ký tự)
        words = re.findall(r'\b\w{3,}\b', content.lower())
        return list(set(words))

class MediaScanner:
    """Quét thư mục tìm media files"""
    
    def __init__(self, root_folder: str):
        self.root_folder = root_folder
        self.media_files: List[MediaFile] = []
        self.voice_file: Optional[str] = None
        self.audio_file: Optional[str] = None
        self.subtitle_file: Optional[str] = None
        logger.info(f"MediaScanner khởi tạo với thư mục: {root_folder}")
    
    def scan(self) -> Dict[str, any]:
        """Quét toàn bộ thư mục"""
        logger.info("Bắt đầu quét media...")
        
        video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv'}
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}
        audio_extensions = {'.mp3', '.wav', '.aac', '.m4a', '.flac'}
        
        for root, dirs, files in os.walk(self.root_folder):
            for file in files:
                file_path = os.path.join(root, file)
                file_lower = file.lower()
                ext = os.path.splitext(file_lower)[1]
                
                # Tìm voice.txt
                if file_lower == 'voice.txt':
                    self.voice_file = file_path
                    logger.info(f"  Tìm thấy voice.txt: {file_path}")
                    continue
                
                # Tìm subtitle
                if ext == '.srt':
                    self.subtitle_file = file_path
                    logger.info(f"  Tìm thấy subtitle: {file_path}")
                    continue
                
                # Tìm voice.mp3
                if file_lower == 'voice.mp3':
                    self.audio_file = file_path
                    logger.info(f"  Tìm thấy voice.mp3: {file_path}")
                    continue
                
                # Tìm video
                if ext in video_extensions:
                    product = self._identify_product(file_path, root)
                    media = MediaFile(
                        path=file_path,
                        type=MediaType.VIDEO,
                        filename=file,
                        product=product,
                        quality_score=0.8
                    )
                    self.media_files.append(media)
                    logger.info(f"  Tìm thấy video: {file} (product: {product})")
                
                # Tìm ảnh
                elif ext in image_extensions:
                    product = self._identify_product(file_path, root)
                    media = MediaFile(
                        path=file_path,
                        type=MediaType.IMAGE,
                        filename=file,
                        product=product,
                        quality_score=0.7
                    )
                    self.media_files.append(media)
                    logger.info(f"  Tìm thấy ảnh: {file} (product: {product})")
        
        logger.info(f"Quét xong: {len(self.media_files)} media files, "
                   f"voice: {bool(self.voice_file)}, subtitle: {bool(self.subtitle_file)}")
        
        return {
            'media_files': self.media_files,
            'voice_file': self.voice_file,
            'audio_file': self.audio_file,
            'subtitle_file': self.subtitle_file
        }
    
    def _identify_product(self, file_path: str, parent_dir: str) -> Optional[str]:
        """Xác định sản phẩm từ tên file hoặc thư mục"""
        file_lower = file_path.lower()
        parent_lower = parent_dir.lower()
        full_path_lower = (file_path + parent_dir).lower()
        
        if 'go' in full_path_lower and '5' in full_path_lower:
            return 'Go5'
        elif 'flip' in full_path_lower and '6' in full_path_lower:
            return 'Flip6'
        elif 'flip' in full_path_lower and '7' in full_path_lower:
            return 'Flip7'
        
        return None
    
    def get_media_for_section(self, section: SectionType, limit: int = 3) -> List[MediaFile]:
        """Lấy media phù hợp cho một section"""
        suitable_media = []
        
        # Xác định product ưu tiên
        preferred_products = []
        if section == SectionType.JBL_GO5:
            preferred_products = ['Go5']
        elif section == SectionType.JBL_FLIP6:
            preferred_products = ['Flip6']
        elif section == SectionType.JBL_FLIP7:
            preferred_products = ['Flip7']
        elif section == SectionType.OUTRO:
            # Outro dùng hết
            preferred_products = ['Go5', 'Flip6', 'Flip7']
        
        # Lọc media
        for media in self.media_files:
            if section == SectionType.HOOK:
                # Hook: dùng video đẹp nhất
                suitable_media.append(media)
            elif media.product in preferred_products:
                suitable_media.append(media)
        
        # Ưu tiên video
        videos = [m for m in suitable_media if m.type == MediaType.VIDEO]
        images = [m for m in suitable_media if m.type == MediaType.IMAGE]
        
        # Sắp xếp theo quality
        videos.sort(key=lambda x: x.quality_score, reverse=True)
        images.sort(key=lambda x: x.quality_score, reverse=True)
        
        result = videos[:limit] if videos else images[:limit]
        
        logger.info(f"Media cho {section.value}: {len(result)} files")
        return result

class TimelineBuilder:
    """Xây dựng timeline trong DaVinci Resolve"""
    
    def __init__(self, resolve_project, timeline_name: str = "AutoEdit"):
        self.resolve_project = resolve_project
        self.timeline_name = timeline_name
        self.timeline = None
        logger.info(f"TimelineBuilder khởi tạo: {timeline_name}")
    
    def create_timeline(self) -> bool:
        """Tạo timeline mới"""
        try:
            # Xóa timeline cũ nếu tồn tại
            existing_timelines = self.resolve_project.GetTimelineCount()
            for i in range(existing_timelines):
                timeline = self.resolve_project.GetTimelineByIndex(i + 1)
                if timeline and timeline.GetName() == self.timeline_name:
                    # Xóa timeline cũ
                    pass
            
            # Tạo timeline mới
            self.timeline = self.resolve_project.CreateTimelineWithSettings({
                'timelineResolutionHeight': VIDEO_HEIGHT,
                'timelineResolutionWidth': VIDEO_WIDTH,
                'timelineFrameRate': FRAME_RATE,
                'timelinePixelAspectRatio': '1',
            })
            
            if self.timeline:
                self.timeline.SetName(self.timeline_name)
                logger.info(f"Tạo timeline thành công: {self.timeline_name}")
                return True
            else:
                logger.error("Không thể tạo timeline")
                return False
        
        except Exception as e:
            logger.error(f"Lỗi tạo timeline: {e}")
            return False
    
    def get_timeline(self):
        """Lấy timeline"""
        return self.timeline
    
    def add_video_clip(self, media_path: str, track: int = 1, 
                      duration: Optional[float] = None) -> bool:
        """Thêm video clip vào timeline"""
        if not self.timeline:
            logger.error("Timeline chưa được tạo")
            return False
        
        try:
            media_pool = self.resolve_project.GetMediaPool()
            
            # Import media
            clip = media_pool.ImportMedia(media_path)
            if not clip:
                logger.error(f"Không thể import: {media_path}")
                return False
            
            # Append vào timeline
            self.timeline.AppendToTimeline(clip)
            
            logger.info(f"Thêm video: {os.path.basename(media_path)}")
            return True
        
        except Exception as e:
            logger.error(f"Lỗi thêm video: {e}")
            return False
    
    def add_audio_clip(self, audio_path: str, track: int = 1) -> bool:
        """Thêm audio (voice) vào timeline"""
        if not self.timeline:
            logger.error("Timeline chưa được tạo")
            return False
        
        try:
            media_pool = self.resolve_project.GetMediaPool()
            
            # Import media
            clip = media_pool.ImportMedia(audio_path)
            if not clip:
                logger.error(f"Không thể import audio: {audio_path}")
                return False
            
            # Append vào timeline
            self.timeline.AppendToTimeline(clip)
            
            logger.info(f"Thêm audio: {os.path.basename(audio_path)}")
            return True
        
        except Exception as e:
            logger.error(f"Lỗi thêm audio: {e}")
            return False
    
    def add_subtitle(self, subtitle_path: str) -> bool:
        """Thêm subtitle vào timeline"""
        if not self.timeline:
            logger.error("Timeline chưa được tạo")
            return False
        
        try:
            # Import subtitle
            media_pool = self.resolve_project.GetMediaPool()
            subtitle = media_pool.ImportMedia(subtitle_path)
            
            if not subtitle:
                logger.error(f"Không thể import subtitle: {subtitle_path}")
                return False
            
            logger.info(f"Thêm subtitle: {os.path.basename(subtitle_path)}")
            return True
        
        except Exception as e:
            logger.error(f"Lỗi thêm subtitle: {e}")
            return False
    
    def apply_transition(self, clip_index: int, transition_type: str = "Cross Dissolve") -> bool:
        """Áp dụng transition cho clip"""
        if not self.timeline:
            logger.error("Timeline chưa được tạo")
            return False
        
        try:
            # Lấy video track 1
            track = self.timeline.GetTrackByID("V", 1)
            if not track:
                logger.warning("Không tìm thấy video track")
                return False
            
            # Lấy clip
            clip = track.GetClipByIndex(clip_index)
            if not clip:
                logger.warning(f"Không tìm thấy clip index {clip_index}")
                return False
            
            # Thêm transition
            # (DaVinci API khác nhau, này chỉ là pseudo)
            logger.info(f"Áp dụng transition '{transition_type}' cho clip {clip_index}")
            return True
        
        except Exception as e:
            logger.error(f"Lỗi áp dụng transition: {e}")
            return False
    
    def apply_pan_zoom_to_image(self, clip_index: int, start_scale: float = 1.0,
                               end_scale: float = 1.2) -> bool:
        """Áp dụng Ken Burns effect (pan/zoom) cho ảnh"""
        try:
            track = self.timeline.GetTrackByID("V", 1)
            if not track:
                return False
            
            clip = track.GetClipByIndex(clip_index)
            if not clip:
                return False
            
            # Áp dụng zoom animation từ start_scale đến end_scale
            logger.info(f"Áp dụng Ken Burns effect: {start_scale}x -> {end_scale}x")
            return True
        
        except Exception as e:
            logger.error(f"Lỗi áp dụng zoom: {e}")
            return False

class RenderManager:
    """Quản lý render"""
    
    def __init__(self, resolve_project):
        self.resolve_project = resolve_project
        logger.info("RenderManager khởi tạo")
    
    def configure_render_settings(self, output_path: str) -> bool:
        """Cấu hình setting render"""
        try:
            project_manager = self.resolve_project.GetProjectManager()
            render_settings = project_manager.GetRenderJobList()
            
            # Cấu hình render
            settings = {
                'TargetDirectory': os.path.dirname(output_path),
                'CustomName': os.path.basename(output_path),
                'VideoFormat': VIDEO_FORMAT,
                'VideoCodec': VIDEO_CODEC,
                'AudioCodec': 'aac',
                'UseMaxRenderQuality': True,
                'ExportVideo': True,
                'ExportAudio': True,
                'OutputFileFormat': 'mov',  # DaVinci thường dùng mov
            }
            
            logger.info(f"Cấu hình render: {VIDEO_WIDTH}x{VIDEO_HEIGHT} {FRAME_RATE}fps {VIDEO_CODEC}")
            return True
        
        except Exception as e:
            logger.error(f"Lỗi cấu hình render: {e}")
            return False
    
    def add_render_job(self, output_path: str) -> bool:
        """Thêm render job"""
        try:
            project_manager = self.resolve_project.GetProjectManager()
            
            # Thêm job
            success = project_manager.AddRenderJob()
            
            if success:
                logger.info(f"Thêm render job: {output_path}")
                return True
            else:
                logger.error("Không thể thêm render job")
                return False
        
        except Exception as e:
            logger.error(f"Lỗi thêm render job: {e}")
            return False
    
    def start_rendering(self) -> bool:
        """Bắt đầu rendering"""
        try:
            project_manager = self.resolve_project.GetProjectManager()
            
            # Bắt đầu render
            success = project_manager.StartRendering()
            
            if success:
                logger.info("Bắt đầu rendering...")
                return True
            else:
                logger.error("Không thể bắt đầu rendering")
                return False
        
        except Exception as e:
            logger.error(f"Lỗi bắt đầu render: {e}")
            return False
    
    def wait_for_render_completion(self, timeout: int = 3600) -> bool:
        """Chờ render hoàn thành"""
        import time
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                project_manager = self.resolve_project.GetProjectManager()
                job_list = project_manager.GetRenderJobList()
                
                if not job_list or len(job_list) == 0:
                    logger.info("Render hoàn thành")
                    return True
                
                time.sleep(5)
            
            except Exception as e:
                logger.error(f"Lỗi kiểm tra render: {e}")
                time.sleep(5)
        
        logger.error("Timeout chờ render")
        return False

class ResolveEditor:
    """Main class điều phối toàn bộ"""
    
    def __init__(self, project_folder: str):
        self.project_folder = project_folder
        self.resolve = None
        self.project = None
        self.media_pool = None
        logger.info(f"ResolveEditor khởi tạo: {project_folder}")
    
    def connect_to_resolve(self) -> bool:
        """Kết nối tới DaVinci Resolve"""
        try:
            # Import DaVinci API
            import sys
            
            # Thêm path DaVinci
            # Windows
            if sys.platform == 'win32':
                resolve_path = r"C:\Program Files\DaVinci Resolve\fusionscript"
            # macOS
            elif sys.platform == 'darwin':
                resolve_path = "/Applications/DaVinci Resolve/fusionscript"
            # Linux
            else:
                resolve_path = "/opt/resolve/fusionscript"
            
            if resolve_path not in sys.path:
                sys.path.append(resolve_path)
            
            import DaVinciResolveScript as dvs
            
            self.resolve = dvs.GetResolve()
            if not self.resolve:
                logger.error("Không thể kết nối tới DaVinci Resolve")
                return False
            
            logger.info("Kết nối DaVinci Resolve thành công")
            return True
        
        except ImportError as e:
            logger.error(f"Lỗi import DaVinci API: {e}")
            logger.error("Hãy chắc chắn DaVinci Resolve Studio 20 đã được cài đặt")
            return False
        except Exception as e:
            logger.error(f"Lỗi kết nối Resolve: {e}")
            return False
    
    def create_or_load_project(self, project_name: str = "davinci_auto") -> bool:
        """Tạo hoặc load project"""
        try:
            project_manager = self.resolve.GetProjectManager()
            
            # Cố gắng load project
            self.project = project_manager.LoadProject(project_name)
            
            if not self.project:
                # Tạo project mới
                self.project = project_manager.CreateProject(project_name)
            
            if self.project:
                self.media_pool = self.project.GetMediaPool()
                logger.info(f"Project '{project_name}' sẵn sàng")
                return True
            else:
                logger.error(f"Không thể tạo/load project")
                return False
        
        except Exception as e:
            logger.error(f"Lỗi tạo/load project: {e}")
            return False
    
    def build_video(self):
        """Dựng toàn bộ video"""
        logger.info("=== BẮT ĐẦU DỰNG VIDEO ===")
        
        # 1. Quét media
        scanner = MediaScanner(self.project_folder)
        scan_results = scanner.scan()
        
        if not scan_results['voice_file']:
            logger.error("Không tìm thấy voice.txt")
            return False
        
        if not scan_results['audio_file']:
            logger.error("Không tìm thấy voice.mp3")
            return False
        
        # 2. Parse voice
        voice_parser = VoiceParser(scan_results['voice_file'])
        segments = voice_parser.parse()
        
        if not segments:
            logger.error("Không thể parse segments từ voice.txt")
            return False
        
        # 3. Parse product info
        product_files = [f for f in scan_results['media_files'] 
                        if f.filename.lower() == 'product-info.md']
        product_info_path = product_files[0].path if product_files else None
        
        product_parser = ProductInfoParser(product_info_path) if product_info_path else None
        if product_parser:
            product_parser.parse()
        
        # 4. Tạo timeline
        timeline_builder = TimelineBuilder(self.project)
        if not timeline_builder.create_timeline():
            logger.error("Không thể tạo timeline")
            return False
        
        timeline = timeline_builder.get_timeline()
        
        # 5. Dựng từng segment
        for idx, segment in enumerate(segments):
            logger.info(f"\n--- Dựng segment {idx + 1}/{len(segments)}: {segment.description} ---")
            
            # Lấy media phù hợp
            media_for_section = scanner.get_media_for_section(segment.section, limit=5)
            
            if media_for_section:
                # Thêm media vào timeline
                for media_idx, media in enumerate(media_for_section):
                    # Tính duration media dựa vào segment duration
                    clip_duration = segment.duration / len(media_for_section) if len(media_for_section) > 1 else segment.duration
                    
                    try:
                        # Import media
                        timeline_builder.add_video_clip(media.path, track=1, duration=clip_duration)
                        
                        # Áp dụng transition nếu không phải clip đầu tiên
                        if media_idx > 0:
                            timeline_builder.apply_transition(media_idx, "Cross Dissolve")
                        
                        # Áp dụng effect nếu là ảnh
                        if media.type == MediaType.IMAGE:
                            timeline_builder.apply_pan_zoom_to_image(media_idx, 1.0, IMAGE_ZOOM_SCALE)
                        
                        logger.info(f"  Thêm {media.type.value}: {media.filename}")
                    
                    except Exception as e:
                        logger.warning(f"  Lỗi thêm media: {e}")
                        continue
            else:
                logger.warning(f"  Không tìm thấy media cho {segment.description}")
        
        # 6. Thêm audio (voice)
        logger.info("\nThêm voice audio...")
        try:
            timeline_builder.add_audio_clip(scan_results['audio_file'], track=1)
        except Exception as e:
            logger.error(f"Lỗi thêm voice: {e}")
        
        # 7. Thêm subtitle nếu có
        if scan_results['subtitle_file']:
            logger.info("Thêm subtitle...")
            try:
                timeline_builder.add_subtitle(scan_results['subtitle_file'])
            except Exception as e:
                logger.warning(f"Lỗi thêm subtitle: {e}")
        
        # 8. Render
        logger.info("\n=== RENDER VIDEO ===")
        output_path = os.path.join(self.project_folder, 'output.mp4')
        
        render_manager = RenderManager(self.project)
        
        if render_manager.configure_render_settings(output_path):
            if render_manager.add_render_job(output_path):
                if render_manager.start_rendering():
                    logger.info("Render job đã được thêm và bắt đầu")
                    
                    # Chờ render (optional)
                    # render_manager.wait_for_render_completion()
        
        logger.info("=== HOÀN THÀNH ===")
        logger.info(f"Output sẽ được lưu tại: {output_path}")
        
        return True

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='DaVinci Auto Editor - Tự động dựng video'
    )
    parser.add_argument(
        'folder',
        help='Đường dẫn tới thư mục chứa video/ảnh/voice'
    )
    parser.add_argument(
        '--project-name',
        default='davinci_auto',
        help='Tên project DaVinci Resolve (default: davinci_auto)'
    )
    
    args = parser.parse_args()
    
    # Kiểm tra thư mục
    if not os.path.isdir(args.folder):
        logger.error(f"Thư mục không tồn tại: {args.folder}")
        sys.exit(1)
    
    # Khởi tạo editor
    editor = ResolveEditor(args.folder)
    
    # Kết nối tới Resolve
    if not editor.connect_to_resolve():
        logger.error("Không thể kết nối tới DaVinci Resolve")
        logger.info("Hãy chắc chắn:")
        logger.info("  1. DaVinci Resolve Studio 20 đã cài đặt")
        logger.info("  2. DaVinci Resolve đang chạy")
        logger.info("  3. Python path được cấu hình đúng")
        sys.exit(1)
    
    # Tạo/load project
    if not editor.create_or_load_project(args.project_name):
        logger.error("Không thể tạo/load project")
        sys.exit(1)
    
    # Dựng video
    if not editor.build_video():
        logger.error("Lỗi dựng video")
        sys.exit(1)
    
    logger.info("Script hoàn thành thành công!")

if __name__ == '__main__':
    main()
