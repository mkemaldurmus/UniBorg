import json
import logging
import mimetypes
import os
import re
import subprocess
from datetime import datetime
from io import BytesIO
from time import sleep
import time
from telethon.tl.types import DocumentAttributeVideo, MessageMediaPhoto
import asyncio
import psutil
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from pyDownload import Downloader
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from sample_config import Config
from uniborg.events import register
from uniborg.util import admin_cmd
from uniborg.util import progress
TEMP_DOWNLOAD_DIRECTORY = Config.TMP_DOWNLOAD_DIRECTORY
GDRIVE_FOLDER = Config.GDRIVE_FOLDER_ID
EDIT_SLEEP_TIME_OUT = 10

logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.WARNING)

async def progress_url(current, total):
    """ Logs the download progress """
    logger.info("Downloaded %s of %s\nCompleted %s", current, total,
              (current / total) * 100)
    prog = "Downloaded {} of {}\nCompleted {}".format(current,total,current / total * 100)
    await asyncio.sleep(EDIT_SLEEP_TIME_OUT)
    return prog


async def download_from_url(url: str, file_name: str) -> str:
    """
    Download files from URL
    """
    start = datetime.now()
    downloader = Downloader(url=url)
    if downloader.is_running:
        sleep(1)
    end = datetime.now()
    duration = (end - start).seconds
    os.rename(downloader.file_name, file_name)
    status = f"Downloaded `{file_name}` in {duration} seconds."
    return status


async def download_from_tg(target_file) -> (str, BytesIO):
    """
    Download files from Telegram
    """
    async def dl_file(buffer: BytesIO) -> BytesIO:
        buffer = await target_file.client.download_media(
            reply_msg,
            buffer,
            progress_callback=progress,
        )
        return buffer

    start = datetime.now()
    buf = BytesIO()
    reply_msg = await target_file.get_reply_message()
    avail_mem = psutil.virtual_memory().available + psutil.swap_memory().free
    try:
        if reply_msg.media.document.size >= avail_mem:  # unlikely to happen but baalaji crai
            filen = await target_file.client.download_media(
                reply_msg,
                progress_callback=progress,
            )
        else:
            buf = await dl_file(buf)
            filen = reply_msg.media.document.attributes[0].file_name
    except AttributeError:
        buf = await dl_file(buf)
        try:
            filen = reply_msg.media.document.attributes[0].file_name
        except AttributeError:
            if isinstance(reply_msg.media, MessageMediaPhoto):
                filen = 'photo-' + str(datetime.today())\
                    .split('.')[0].replace(' ', '-') + '.jpg'
            else:
                filen = reply_msg.media.document.mime_type\
                    .replace('/', '-' + str(datetime.today())
                             .split('.')[0].replace(' ', '-') + '.')
    end = datetime.now()
    duration = (end - start).seconds
    await target_file.edit(f"Downloaded `{filen}` in {duration} seconds.")
    return filen, buf


async def gdrive_upload(filename: str, filebuf: BytesIO = None) -> str:
    """
    Upload files to Google Drive using PyDrive
    """
    # a workaround for disabling cache errors
    # https://github.com/googleapis/google-api-python-client/issues/299
    logging.getLogger('googleapiclient.discovery_cache').setLevel(
        logging.CRITICAL)

    # Authenticate Google Drive automatically
    # https://stackoverflow.com/a/24542604
    gauth = GoogleAuth()
    # Try to load saved client credentials
    gauth.LoadCredentialsFile("secret.json")
    if gauth.credentials is None:
        return "nosecret"
    if gauth.access_token_expired:
        gauth.Refresh()
    else:
        # Initialize the saved credentials
        gauth.Authorize()
    # Save the current credentials to a file
    gauth.SaveCredentialsFile("secret.json")
    drive = GoogleDrive(gauth)

    if filename.count('/') > 1:
        filename = filename.split('/')[-1]
    filedata = {
        'title': filename,
        "parents": [{
            "kind": "drive#fileLink",
            "id": GDRIVE_FOLDER
        }]
    }

    if filebuf:
        mime_type = mimetypes.guess_type(filename)
        if mime_type[0] and mime_type[1]:
            filedata['mimeType'] = f"{mime_type[0]}/{mime_type[1]}"
        else:
            filedata['mimeType'] = 'text/plain'
        file = drive.CreateFile(filedata)
        file.content = filebuf
    else:
        file = drive.CreateFile(filedata)
        file.SetContentFile(filename)
    name = filename.split('/')[-1]
    file.Upload()
    # insert new permission
    file.InsertPermission({
        'type': 'anyone',
        'value': 'anyone',
        'role': 'reader'
    })
    if not filebuf:
        os.remove(filename)
    reply = f"[{name}]({file['alternateLink']})\n" \
        f"__Direct link:__ [Here]({file['downloadUrl']})"
    return reply


# @register(pattern=r"^.mirror(?: |$)([\s\S]*)", outgoing=True)
async def gdrive_mirror(request):
    """ Download a file and upload to Google Drive """
    message = request.pattern_match.group(1)
    if not request.reply_to_msg_id and not message:
        await request.edit("`Usage: .mirror <url> <url>`")
        return
    reply = ''
    reply_msg = await request.get_reply_message()
    links = re.findall(r'\bhttps?://.*\.\S+', message)
    if not (links or reply_msg or reply_msg.media or reply_msg.media.document):
        reply = "`No links or telegram files found!`\n"
        await request.edit(reply)
        return
    if request.reply_to_msg_id:
        await request.edit('`Downloading from Telegram...`')
        filen, buf = await download_from_tg(request)
        await request.edit(f'`Uploading {filen} to GDrive...`')
        reply += await gdrive_upload(
            filen, buf) if buf else await gdrive_upload(filen)
    elif "|" in message:
        url, file_name = message.split("|")
        url = url.strip()
        file_name = file_name.strip()
        await request.edit(f'`Downloading {file_name}`')
        status = await download_from_url(url, file_name)
        await request.edit(status)
        await request.edit(f'`Uploading {file_name} to GDrive...`')
        reply += await gdrive_upload(file_name)
    if "nosecret" in reply:
        reply = "`Run the generate_drive_session.py file " \
                "in your machine to authenticate on google drive!!`"
        await request.edit(reply)


# @register(pattern=r"^.drive(?: |$)(\S*.?\/*.?\.?[A-Za-z0-9]*)", outgoing=True)
async def gdrive(request):
    """ Upload files from server to Google Drive """
    path = request.pattern_match.group(1)
    if not path:
        await request.edit("`Usage: .drive <file>`")
        return
    if not os.path.isfile(path):
        await request.edit("`No such file!`\n")
        return
    file_name = path.split('/')[-1]
    await request.edit(f'`Uploading {file_name} to GDrive...`')
    reply = await gdrive_upload(path)
    await request.edit(reply)


# @register(pattern=r"^.download(?: |$)(.*)", outgoing=True)
@borg.on(admin_cmd(pattern="jdownload ?(.*)"))
async def download(target_file):
    """ For .download command, download files to the userbot's server. """
    if not target_file.text[0].isalpha() and target_file.text[0] not in ("/", "#", "@", "!"):
        if target_file.fwd_from:
            return
        mone = await target_file.edit("Processing ...")
        input_str = target_file.pattern_match.group(1)
        if not os.path.isdir(TEMP_DOWNLOAD_DIRECTORY):
            os.makedirs(TEMP_DOWNLOAD_DIRECTORY)
        if target_file.reply_to_msg_id:
            start = datetime.now()
            c_time = time.time()
            downloaded_file_name = await target_file.client.download_media(
                await target_file.get_reply_message(),
                TEMP_DOWNLOAD_DIRECTORY,
                progress_callback=lambda d, t: asyncio.get_event_loop().create_task(
                    progress(d, t, mone, c_time, "trying to download")
                ),
            )
            end = datetime.now()
            duration = (end - start).seconds
            await target_file.edit(
                "Downloaded to `{}` in {} seconds.".format(downloaded_file_name, duration)
            )
        elif "|" in input_str:
            url, file_name = input_str.split("|")
            url = url.strip()
            # https://stackoverflow.com/a/761825/4723940
            file_name = file_name.strip()
            required_file_name = TEMP_DOWNLOAD_DIRECTORY + "" + file_name
            start = datetime.now()
            resp = requests.get(url, stream=True)
            with open(required_file_name, "wb") as file:
                total_length = resp.headers.get("content-length")
                # https://stackoverflow.com/a/15645088/4723940
                if total_length is None:  # no content length header
                    file.write(resp.content)
                else:
                    downloaded = 0
                    total_length = int(total_length)
                    for chunk in resp.iter_content(chunk_size=128):
                        downloaded += len(chunk)
                        file.write(chunk)
                        done = int(100 * downloaded / total_length)
                        download_progress_string = "Downloading ... [%s%s]" % (
                            "=" * done,
                            " " * (50 - done),
                        )
                        LOGS.info(download_progress_string)
            end = datetime.now()
            duration = (end - start).seconds
            await target_file.edit(
                "Downloaded to `{}` in {} seconds.".format(required_file_name, duration)
            )
        else:
            await target_file.edit("Reply to a message to download to my local server.")


# @borg.on(admin_cmd(pattern="download ?(.*)", allow_sudo=True))
# async def _(event):
#     if event.fwd_from:
#         return
#     mone = await event.edit("Processing ...")
#     input_str = event.pattern_match.group(1)
#     if not os.path.isdir(Config.TMP_DOWNLOAD_DIRECTORY):
#         os.makedirs(Config.TMP_DOWNLOAD_DIRECTORY)
#     if event.reply_to_msg_id:
#         start = datetime.now()
#         reply_message = await event.get_reply_message()
#         try:
#             c_time = time.time()
#             filen, buf = await download_from_tg(target_file)
#             downloaded_file_name = await borg.download_media(
#                 reply_message,
#                 Config.TMP_DOWNLOAD_DIRECTORY,
#                 progress_callback=lambda d, t: asyncio.get_event_loop().create_task(
#                     progress(d, t, mone, c_time, "trying to download")
#                 )
#             )
#         except Exception as e:  # pylint:disable=C0103,W0703
#             await mone.edit(str(e))
#         else:
#             end = datetime.now()
#             ms = (end - start).seconds
#             await mone.edit("Downloaded to `{}` in {} seconds.".format(downloaded_file_name, ms))
#     elif input_str:
#         start = datetime.now()
#         url = input_str
#         file_name = os.path.basename(url)
#         to_download_directory = Config.TMP_DOWNLOAD_DIRECTORY
#         if "|" in input_str:
#             url, file_name = input_str.split("|")
#         url = url.strip()
#         file_name = file_name.strip()
#         downloaded_file_name = os.path.join(to_download_directory, file_name)
#         downloader = SmartDL(url, downloaded_file_name, progress_bar=False)
#         downloader.start(blocking=False)
#         display_message = ""
#         c_time = time.time()
#         while not downloader.isFinished():
#             total_length = downloader.filesize if downloader.filesize else None
#             downloaded = downloader.get_dl_size()
#             now = time.time()
#             diff = now - c_time
#             percentage = downloader.get_progress() * 100
#             speed = downloader.get_speed()
#             elapsed_time = round(diff) * 1000
#             progress_str = "[{0}{1}]\nProgress: {2}%".format(
#                 ''.join(["█" for i in range(math.floor(percentage / 5))]),
#                 ''.join(["░" for i in range(20 - math.floor(percentage / 5))]),
#                 round(percentage, 2))
#             estimated_total_time = downloader.get_eta(human=True)
#             try:
#                 current_message = f"trying to download\n"
#                 current_message += f"URL: {url}\n"
#                 current_message += f"File Name: {file_name}\n"
#                 current_message += f"{progress_str}\n"
#                 current_message += f"{humanbytes(downloaded)} of {humanbytes(total_length)}\n"
#                 current_message += f"ETA: {estimated_total_time}"
#                 if round(diff % 10.00) == 0 and current_message != display_message:
#                     await mone.edit(current_message)
#                     display_message = current_message
#             except Exception as e:
#                 logger.info(str(e))
#         end = datetime.now()
#         ms = (end - start).seconds
#         if os.path.exists(downloaded_file_name):
#             await mone.edit("Downloaded to `{}` in {} seconds.".format(downloaded_file_name, ms))
#         else:
#             await mone.edit("Incorrect URL\n {}".format(input_str))
#     else:
#         await mone.edit("Reply to a message to download to my local server.")



# @register(pattern=r"^.uploadir (.*)", outgoing=True)
async def uploadir(udir_event):
    """ For .uploadir command, allows you to upload
     everything from a folder in the server"""
    if udir_event.fwd_from:
        return
    input_str = udir_event.pattern_match.group(1)
    if os.path.exists(input_str):
        start = datetime.now()
        await udir_event.edit("Processing ...")
        lst_of_files = []
        for r, d, f in os.walk(input_str):
            for file in f:
                lst_of_files.append(os.path.join(r, file))
            for file in d:
                lst_of_files.append(os.path.join(r, file))
        LOGS.info(lst_of_files)
        uploaded = 0
        await udir_event.edit("Found {} files. Uploading will \
                start soon. Please wait!".format(len(lst_of_files)))
        for single_file in lst_of_files:
            if os.path.exists(single_file):
                # https://stackoverflow.com/a/678242/4723940
                caption_rts = os.path.basename(single_file)
                if not caption_rts.lower().endswith(".mp4"):
                    await udir_event.client.send_file(
                        udir_event.chat_id,
                        single_file,
                        caption=caption_rts,
                        force_document=False,
                        allow_cache=False,
                        reply_to=udir_event.message.id,
                        progress_callback=progress,
                    )
                else:
                    thumb_image = os.path.join(input_str, "thumb.jpg")
                    metadata = extractMetadata(createParser(single_file))
                    duration = 0
                    width = 0
                    height = 0
                    if metadata.has("duration"):
                        duration = metadata.get("duration").seconds
                    if metadata.has("width"):
                        width = metadata.get("width")
                    if metadata.has("height"):
                        height = metadata.get("height")
                    await udir_event.client.send_file(
                        udir_event.chat_id,
                        single_file,
                        caption=caption_rts,
                        thumb=thumb_image,
                        force_document=False,
                        allow_cache=False,
                        reply_to=udir_event.message.id,
                        attributes=[
                            DocumentAttributeVideo(
                                duration=duration,
                                w=width,
                                h=height,
                                round_message=False,
                                supports_streaming=True,
                            )
                        ],
                        progress_callback=progress,
                    )
                os.remove(single_file)
                uploaded = uploaded + 1
        end = datetime.now()
        duration = (end - start).seconds
        await udir_event.edit("Uploaded {} files in {} seconds.".format(
            uploaded, duration))
    else:
        await udir_event.edit("404: Directory Not Found")


# @register(pattern=r"^.upload (.*)", outgoing=True)
async def upload(u_event):
    """ For .upload command, allows you to \
    upload a file from the userbot's server """
    if u_event.fwd_from:
        return
    if u_event.is_channel and not u_event.is_group:
        await u_event.edit("`Uploading isn't permitted on channels`")
        return
    await u_event.edit("Processing ...")
    input_str = u_event.pattern_match.group(1)
    if input_str in ("userbot.session", "config.env"):
        await u_event.edit("`That's a dangerous operation! Not Permitted!`")
        return
    if os.path.exists(input_str):
        start = datetime.now()
        await u_event.client.send_file(
            u_event.chat_id,
            input_str,
            force_document=True,
            allow_cache=False,
            reply_to=u_event.message.id,
            progress_callback=progress,
        )
        end = datetime.now()
        duration = (end - start).seconds
        await u_event.edit("Uploaded in {} seconds.".format(duration))
    else:
        await u_event.edit("404: File Not Found")


def get_video_thumb(file, output=None, width=90):
    """ Get video thhumbnail """
    metadata = extractMetadata(createParser(file))
    popen = subprocess.Popen(
        [
            "ffmpeg",
            "-i",
            file,
            "-ss",
            str(
                int((0, metadata.get("duration").seconds
                     )[metadata.has("duration")] / 2)),
            "-filter:v",
            "scale={}:-1".format(width),
            "-vframes",
            "1",
            output,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if not popen.returncode and os.path.lexists(file):
        return output
    return None


def extract_w_h(file):
    """ Get width and height of media """
    command_to_run = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        file,
    ]
    # https://stackoverflow.com/a/11236144/4723940
    try:
        t_response = subprocess.check_output(command_to_run,
                                             stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        LOGS.warning(exc)
    else:
        x_reponse = t_response.decode("UTF-8")
        response_json = json.loads(x_reponse)
        width = int(response_json["streams"][0]["width"])
        height = int(response_json["streams"][0]["height"])
        return width, height


# @register(pattern=r"^.uploadas(stream|vn|all) (.*)", outgoing=True)
async def uploadas(uas_event):
    """ For .uploadas command, allows you \
    to specify some arguments for upload. """
    if uas_event.fwd_from:
        return
    await uas_event.edit("Processing ...")
    type_of_upload = uas_event.pattern_match.group(1)
    supports_streaming = False
    round_message = False
    spam_big_messages = False
    if type_of_upload == "stream":
        supports_streaming = True
    if type_of_upload == "vn":
        round_message = True
    if type_of_upload == "all":
        spam_big_messages = True
    input_str = uas_event.pattern_match.group(2)
    thumb = None
    file_name = None
    if "|" in input_str:
        file_name, thumb = input_str.split("|")
        file_name = file_name.strip()
        thumb = thumb.strip()
    else:
        file_name = input_str
        thumb_path = "a_random_f_file_name" + ".jpg"
        thumb = get_video_thumb(file_name, output=thumb_path)
    if os.path.exists(file_name):
        start = datetime.now()
        metadata = extractMetadata(createParser(file_name))
        duration = 0
        width = 0
        height = 0
        if metadata.has("duration"):
            duration = metadata.get("duration").seconds
        if metadata.has("width"):
            width = metadata.get("width")
        if metadata.has("height"):
            height = metadata.get("height")
        try:
            if supports_streaming:
                await uas_event.client.send_file(
                    uas_event.chat_id,
                    file_name,
                    thumb=thumb,
                    caption=input_str,
                    force_document=False,
                    allow_cache=False,
                    reply_to=uas_event.message.id,
                    attributes=[
                        DocumentAttributeVideo(
                            duration=duration,
                            w=width,
                            h=height,
                            round_message=False,
                            supports_streaming=True,
                        )
                    ],
                    progress_callback=progress,
                )
            elif round_message:
                await uas_event.client.send_file(
                    uas_event.chat_id,
                    file_name,
                    thumb=thumb,
                    allow_cache=False,
                    reply_to=uas_event.message.id,
                    video_note=True,
                    attributes=[
                        DocumentAttributeVideo(
                            duration=0,
                            w=1,
                            h=1,
                            round_message=True,
                            supports_streaming=True,
                        )
                    ],
                    progress_callback=progress,
                )
            elif spam_big_messages:
                await uas_event.edit("TBD: Not (yet) Implemented")
                return
            end = datetime.now()
            duration = (end - start).seconds
            os.remove(thumb)
            await uas_event.edit("Uploaded in {} seconds.".format(duration))
        except FileNotFoundError as err:
            await uas_event.edit(str(err))
    else:
        await uas_event.edit("404: File Not Found")