# name: Text-To-Speech
# author: @ItzNeedlemouseNB
# version: 2.3.1
# description: Преобразует текст в голосовое сообщение или mp3 через Google TTS и Edge TTS
# requires: gtts, edge-tts

import os
import tempfile
import asyncio
import time
from gtts import gTTS
from utils import get_args, answer
from edge_tts import Communicate

VOICES_RU = [
    ("ru-RU-DmitryNeural", "Дмитрий (Мужской)"),
    ("ru-RU-SvetlanaNeural", "Светлана (Женский)"),
    ("ru-RU-DariyaNeural", "Дарья (Женский)"),
    ("ru-RU-DmitryNeuralMultilingual", "Дмитрий мультиязычный"),
    ("ru-RU-SergeyNeural", "Сергей (Мужской)")
]

VOICES_EN = [
    ("en-US-AriaNeural", "Ария (Женский)"),
    ("en-US-GuyNeural", "Гай (Мужской)"),
    ("en-US-JennyNeural", "Дженни (Женский)"),
    ("en-GB-SoniaNeural", "Соня (Великобритания)"),
    ("en-GB-RyanNeural", "Райан (Великобритания)")
]

def register(kernel):
    # Вспомогательная функция для генерации TTS с ретраями
    async def generate_tts_with_retry(text, voice, tmp_path, max_retries=2):
        """Генерирует TTS с повторами при ошибке NoAudioReceived"""
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                communicate = Communicate(text, voice)
                await asyncio.wait_for(communicate.save(tmp_path), timeout=20)
                return True
            except Exception as e:
                if "NoAudioReceived" in str(e) and attempt < max_retries:
                    last_error = e
                    await asyncio.sleep(1 + attempt)  # Пауза между попытками
                    continue
                raise e
        raise last_error

    # Команда .tts - озвучивание текста
    @kernel.register.command(
        "tts",
        doc_ru="<текст> Озвучить текст. Флаги: -m (mp3), -g (голосовое). Работает с reply на текст или .txt файл",
        doc_en="<text> Text to speech. Flags: -m (mp3), -g (voice). Works with reply to text or .txt file",
        alias=["texttospeech"]
    )
    async def tts_handler(event):
        try:
            args = get_args(event)
            text = None
            
            # Проверяем reply на сообщение или файл
            if event.is_reply:
                reply_msg = await event.get_reply_message()
                if reply_msg.text:
                    text = reply_msg.text
                elif reply_msg.file and reply_msg.file.name.endswith('.txt'):
                    file_bytes = await reply_msg.download_media(bytes)
                    text = file_bytes.decode('utf-8')
            
            # Если нет reply, берём из аргументов
            if text is None:
                text_parts = []
                for arg in args:
                    if not arg.startswith('-'):
                        text_parts.append(arg)
                text = ' '.join(text_parts).strip()
            
            if not text:
                await answer(event, "⚠️ Укажи текст для озвучки или ответь на сообщение.\nПример: .tts Привет мир\nФлаги: -m (mp3), -g (голосовое)")
                return
            
            # Ограничение длины
            if len(text) > 2000:
                text = text[:2000] + "..."
            
            # Определяем тип вывода
            is_mp3 = '-m' in args
            is_voice = '-g' in args
            
            # Если установлен mp3 по умолчанию и не указан флаг -g, отправляем mp3
            mp3_default = await kernel.db_manager.db_get(__name__, 'mp3_default') or False
            if mp3_default and not is_voice:
                is_mp3 = True
            
            # Получаем настройки провайдера и голоса
            provider = await kernel.db_manager.db_get(__name__, 'provider') or 'edge'
            voice = await kernel.db_manager.db_get(__name__, f'voice_{provider}') or None
            
            # Создаём временный файл
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                tmp_path = tmp.name
            
            try:
                if provider == 'edge':
                    if not voice:
                        voice = "ru-RU-SvetlanaNeural"  # Голос по умолчанию
                    # Используем ретраи для Edge TTS
                    success = await generate_tts_with_retry(text, voice, tmp_path)
                    if not success:
                        raise Exception("Не удалось получить аудио от Edge TTS после 3 попыток")
                else:
                    tts = gTTS(text=text, lang='ru')
                    tts.save(tmp_path)
                
                # Проверяем что файл не пустой и имеет нормальный размер
                file_size = os.path.getsize(tmp_path)
                if file_size < 100:  # Меньше 100 байт - скорее всего ошибка
                    raise Exception(f"Файл слишком маленький ({file_size} байт)")
                
                # Определяем reply_to для всех типов чатов
                reply_to = None
                if event.is_reply:
                    reply_msg = await event.get_reply_message()
                    reply_to = reply_msg.id
                
                if is_mp3:
                    # Отправляем как mp3 файл
                    await event.client.send_file(
                        event.chat_id,
                        tmp_path,
                        force_document=True,
                        reply_to=reply_to
                    )
                else:
                    # Отправляем как голосовое сообщение
                    await event.client.send_file(
                        event.chat_id,
                        tmp_path,
                        voice_note=True,
                        reply_to=reply_to
                    )
                
                # Отправляем уведомление в группах/каналах
                chat_type = "личном сообщении" if event.is_private else ("канале" if event.is_channel and not event.is_group else "группе")
                if not event.is_private:
                    await answer(event, f"✅ Озвучено в {chat_type}")
                
            finally:
                # Удаляем временный файл
                try:
                    os.unlink(tmp_path)
                except:
                    pass
            
            # Удаляем команду
            try:
                await event.delete()
            except:
                pass
                    
        except Exception as e:
            # Специальная обработка для NoAudioReceived
            if "NoAudioReceived" in str(e):
                await answer(event, "⚠️ Edge TTS не смог сгенерировать аудио. Попробуй ещё раз или переключи провайдера командой .tts provider gtts")
            else:
                await kernel.handle_error(e, message="Ошибка в команде tts", event=event)

    # Команда .tts mp3 - сохранение настроек mp3
    @kernel.register.command(
        "tts_mp3",
        doc_ru="Включить отправку TTS как mp3 файл",
        doc_en="Enable sending TTS as mp3 file"
    )
    async def tts_mp3_handler(event):
        try:
            await kernel.db_manager.db_set(__name__, 'mp3_default', True)
            await answer(event, "✅ Теперь TTS будет отправляться как MP3 файл по умолчанию")
        except Exception as e:
            await kernel.handle_error(e, message="Ошибка в команде tts_mp3", event=event)

    # Команда .tts voice - отправка голосовым сообщением (переключатель)
    @kernel.register.command(
        "tts_voice",
        doc_ru="Включить отправку TTS как голосовое сообщение",
        doc_en="Enable sending TTS as voice message"
    )
    async def tts_voice_handler(event):
        try:
            await kernel.db_manager.db_set(__name__, 'mp3_default', False)
            await answer(event, "✅ Теперь TTS будет отправляться как голосовое сообщение по умолчанию")
        except Exception as e:
            await kernel.handle_error(e, message="Ошибка в команде tts_voice", event=event)

    # Команда .tts voices - список голосов
    @kernel.register.command(
        "tts_voices",
        doc_ru="[ru|en] Список доступных голосов",
        doc_en="[ru|en] List of available voices"
    )
    async def tts_voices_handler(event):
        try:
            args = get_args(event)
            lang = args[0] if args else 'ru'
            
            if lang.lower() == 'en':
                voices = VOICES_EN
            else:
                voices = VOICES_RU
            
            # Проверяем текущий голос
            provider = await kernel.db_manager.db_get(__name__, 'provider') or 'edge'
            current_voice = await kernel.db_manager.db_get(__name__, f'voice_{provider}') or None
            
            text = f"🎙 Список голосов ({lang.upper()}):\n\n"
            text += "`Голос` - Название" + ("_(*выбран)_" if current_voice else "") + "\n"
            text += "━━━━━━━━━━━━━━\n\n"
            
            for voice_id, voice_name in voices:
                marker = " ✅" if voice_id == current_voice else ""
                text += f"`{voice_id}` — {voice_name}{marker}\n"
            
            text += "\nИспользуй: .tts set <voice_id> чтобы установить голос"
            
            await answer(event, text)
        except Exception as e:
            await kernel.handle_error(e, message="Ошибка в команде tts_voices", event=event)

    # Команда .tts set - установка голоса
    @kernel.register.command(
        "tts_set",
        doc_ru="<voice_id> Установить голос по умолчанию",
        doc_en="<voice_id> Set default voice"
    )
    async def tts_set_handler(event):
        try:
            args = get_args(event)
            if not args:
                await answer(event, "⚠️ Укажи ID голоса.\nСписок: .tts voices")
                return
            
            voice_id = args[0]
            provider = await kernel.db_manager.db_get(__name__, 'provider') or 'edge'
            
            # Проверяем валидность голоса
            valid_voices = [v[0] for v in VOICES_RU + VOICES_EN]
            if voice_id not in valid_voices:
                await answer(event, f"❌ Голос {voice_id} не найден.\nСписок: .tts voices")
                return
            
            await kernel.db_manager.db_set(__name__, f'voice_{provider}', voice_id)
            await answer(event, f"✅ Голос установлен: {voice_id}")
        except Exception as e:
            await kernel.handle_error(e, message="Ошибка в команде tts_set", event=event)

    # Команда .tts provider - переключение провайдера
    @kernel.register.command(
        "tts_provider",
        doc_ru="<edge|gtts> Переключить провайдер TTS",
        doc_en="<edge|gtts> Switch TTS provider"
    )
    async def tts_provider_handler(event):
        try:
            args = get_args(event)
            if not args:
                await answer(event, "⚠️ Укажи провайдера: edge или gtts")
                return
            
            provider = args[0].lower()
            if provider not in ['edge', 'gtts']:
                await answer(event, "❌ Неверный провайдер. Доступные: edge, gtts")
                return
            
            await kernel.db_manager.db_set(__name__, 'provider', provider)
            
            # Устанавливаем голос по умолчанию для провайдера
            if provider == 'edge' and not await kernel.db_manager.db_get(__name__, 'voice_edge'):
                await kernel.db_manager.db_set(__name__, 'voice_edge', 'ru-RU-SvetlanaNeural')
            elif provider == 'gtts':
                await kernel.db_manager.db_set(__name__, 'voice_gtts', 'ru')
            
            await answer(event, f"✅ Провайдер установлен: {provider}")
        except Exception as e:
            await kernel.handle_error(e, message="Ошибка в команде tts_provider", event=event)

    # Команда .tts info - информация о настройках
    @kernel.register.command(
        "tts_info",
        doc_ru="Текущий провайдер и голос",
        doc_en="Current provider and voice"
    )
    async def tts_info_handler(event):
        try:
            provider = await kernel.db_manager.db_get(__name__, 'provider') or 'edge'
            voice = await kernel.db_manager.db_get(__name__, f'voice_{provider}') or 'Не установлен'
            mp3_default = await kernel.db_manager.db_get(__name__, 'mp3_default') or False
            
            text = f"📊 Настройки TTS:\n"
            text += f"┌ Провайдер: `{provider}`\n"
            text += f"├ Голос: `{voice}`\n"
            text += f"└ MP3 по умолчанию: {'да' if mp3_default else 'нет'}"
            
            await answer(event, text)
        except Exception as e:
            await kernel.handle_error(e, message="Ошибка в команде tts_info", event=event)

    # Команда .tts clear_cache - очистка кэша
    @kernel.register.command(
        "tts_clear_cache",
        doc_ru="Очистить кэш аудио файлов",
        doc_en="Clear audio file cache"
    )
    async def tts_clear_cache_handler(event):
        try:
            cache_dir = tempfile.gettempdir()
            count = 0
            for file in os.listdir(cache_dir):
                if file.startswith('tts_') or file.startswith('tmp'):
                    filepath = os.path.join(cache_dir, file)
                    try:
                        if os.path.isfile(filepath):
                            os.unlink(filepath)
                            count += 1
                    except PermissionError:
                        continue
                    except OSError:
                        continue
            
            await answer(event, f"✅ Кэш очищен. Удалено файлов: {count}")
        except Exception as e:
            await kernel.handle_error(e, message="Ошибка в команде tts_clear_cache", event=event)

    # Фоновый цикл очистки старых временных файлов
    @kernel.register.loop(interval=600, autostart=True)
    async def tts_cleanup_loop(kernel):
        try:
            cache_dir = tempfile.gettempdir()
            current_time = time.time()
            for file in os.listdir(cache_dir):
                if file.startswith('tmp') or file.startswith('tts_'):
                    filepath = os.path.join(cache_dir, file)
                    try:
                        if os.path.isfile(filepath) and current_time - os.path.getmtime(filepath) > 3600:
                            os.unlink(filepath)
                    except PermissionError:
                        continue
                    except OSError:
                        continue
        except Exception:
            pass
