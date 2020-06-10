"plugin credits https://t.me/By_Azade usage: .spot <song name> plugin choose automatically best quality"

import asyncio
import logging
import os
import shutil
import subprocess
from datetime import datetime

from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from sample_config import Config
from uniborg.util import admin_cmd

logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.WARNING)
logger = logging.getLogger(__name__)

DOWNLOAC_LOC = Config.TMP_DOWNLOAD_DIRECTORY + "spotify/"


@borg.on(admin_cmd(pattern="spot ?(.*)"))  # pylint:disable=E0602
async def spoti(event):
    await event.edit("Processing ...")
    music_name = event.pattern_match.group(1)
    if not os.path.exists(DOWNLOAC_LOC):
        os.makedirs(DOWNLOAC_LOC)
    subprocess.Popen(
        ["spotdl", "--song", f"'{music_name}'", "-o", "flac", "-q", "best", "-f", f"{DOWNLOAC_LOC}"])
    # os.system(
    #     f"spotdl --song '{music_name}' -o flac -q best -f {DOWNLOAC_LOC}")
    if os.path.exists(DOWNLOAC_LOC):
        start = datetime.now()

        lst_of_files = sorted(get_lst_of_files(DOWNLOAC_LOC, []))
        logger.info(lst_of_files)
        u = 0
        await event.edit(
            "`Music uploading will start soon. `" +
            "`Please wait!`"
        )
        for single_file in lst_of_files:
            if os.path.exists(single_file):
                force_document = True
                supports_streaming = False
                document_attributes = []
                width = 0
                height = 0
            if single_file.upper().endswith(Config.TL_MUS_STREAM_TYPES):
                metadata = extractMetadata(createParser(single_file))
                duration = 0
                title = ""
                artist = ""
                if metadata.has("duration"):
                    duration = metadata.get('duration').seconds
                if metadata.has("title"):
                    title = metadata.get("title")
                if metadata.has("artist"):
                    artist = metadata.get("artist")
                document_attributes = [
                    DocumentAttributeAudio(
                        duration=duration,
                        voice=False,
                        title=title,
                        performer=artist,
                        waveform=None
                    )
                ]
                supports_streaming = True
                force_document = False
            if not single_file.endswith(".temp"):
                try:
                    caption_text = os.path.splitext(
                        os.path.basename(single_file))[0]
                    await event.client.send_file(
                        event.chat_id,
                        single_file,
                        caption=f"`{caption_text}`",
                        force_document=force_document,
                        supports_streaming=supports_streaming,
                        allow_cache=False,
                        reply_to=event.message.id
                        # thumb=thumb,
                        # attributes=document_attributes,
                        # progress_callback=lambda d, t: asyncio.get_event_loop().create_task(
                        #     progress(d, t, event, c_time, "trying to upload")
                        # )
                    )
                except Exception as e:
                    await event.client.send_message(
                        event.chat_id,
                        "hata `{}`".format(str(e)),
                        reply_to=event.message.id
                    )
                    # some media were having some issues
                    continue
                os.remove(single_file)
                u = u + 1
                await asyncio.sleep(4)
            end = datetime.now()
            ms = (end - start).seconds
            await event.edit("`Uploaded {} music in {} seconds.`".format(u, ms))
            shutil.rmtree(DOWNLOAC_LOC)


def get_lst_of_files(input_directory, output_lst):
    filesinfolder = os.listdir(input_directory)
    for file_name in filesinfolder:
        current_file_name = os.path.join(input_directory, file_name)
        if os.path.isdir(current_file_name):
            return get_lst_of_files(current_file_name, output_lst)
        output_lst.append(current_file_name)
    return output_lst