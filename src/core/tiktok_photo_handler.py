import logging
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

def is_tiktok_photo_url(url: str) -> bool:
    url_lower = url.lower()
    
    if 'tiktok.com' not in url_lower:
        return False
        
    # Если в ссылке явно указано, что это фото
    if '/photo/' in url_lower:
        return True
        
    # Если это короткая ссылка (редирект), мы должны узнать финальный адрес
    if 'vm.tiktok.com' in url_lower or 'vt.tiktok.com' in url_lower:
        try:
            # Делаем быстрый запрос без скачивания (HEAD), чтобы получить полный URL
            response = requests.head(url, allow_redirects=True, timeout=5)
            if '/photo/' in response.url.lower():
                return True
        except Exception as e:
            logger.debug(f"Не удалось раскрыть короткую ссылку TikTok: {e}")
            
    # Если это обычное видео, возвращаем False
    return False

def download_tiktok_photos(url: str, work_dir: Path) -> list[Path]:
    logger.info(f"Запрос фото TikTok через TikWM API: {url}")
    
    try:
        api_url = "https://www.tikwm.com/api/"
        response = requests.post(api_url, data={"url": url, "hd": 1}, timeout=20)
        data = response.json()
        
        if data.get("code") == 0 and "data" in data:
            images = data["data"].get("images", [])
            
            if not images:
                raise ValueError("В этом посте нет фотографий (возможно, это видео).")
                
            downloaded_paths = []
            
            for idx, img_url in enumerate(images):
                try:
                    img_res = requests.get(img_url, timeout=15)
                    if img_res.status_code == 200:
                        file_path = work_dir / f"tiktok_photo_{idx:02d}.jpg"
                        with open(file_path, "wb") as f:
                            f.write(img_res.content)
                        downloaded_paths.append(file_path)
                except Exception as e:
                    logger.warning(f"Не удалось скачать одно из фото ({img_url}): {e}")
                    
            if downloaded_paths:
                logger.info(f"Успешно скачано {len(downloaded_paths)} фото через API.")
                return downloaded_paths
            else:
                raise ValueError("Не удалось сохранить ни одного изображения на диск.")
        else:
            msg = data.get("msg", "Неизвестная ошибка API")
            logger.error(f"TikWM API Error: {msg}")
            raise ValueError(f"API отклонил запрос: {msg}")
            
    except Exception as e:
        logger.error(f"Критическая ошибка при скачивании фото: {e}")
        raise RuntimeError(f"Не удалось получить доступ к TikTok: {str(e)}")
