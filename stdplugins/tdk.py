"""
Turkish word meaning. Only Turkish. Coded @By_Azade
"""

import logging
import os
from datetime import datetime
from telethon import events
from sample_config import Config
from uniborg.util import admin_cmd
import requests
import json

logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.WARNING)

@borg.on(admin_cmd(pattern="tdk ?(.*)"))
async def tdk(event):
    if event.fwd_from:
        return
    inp = event.pattern_match.group(1)
    kelime = "https://sozluk.gov.tr/gts?ara={}".format(inp)
    headers = {"USER-AGENT": "UniBorg"}
    response = requests.get(kelime, headers=headers).json()
    anlam_sayisi = response[0]['anlam_say']
    try:
        x = "TDK Sözlük **{}**\n\n".format(inp)
        for anlamlar in range(int(anlam_sayisi)):
            x += "👉{}\n".format(response[0]['anlamlarListe'][anlamlar]['anlam'])
            # print(x)
        await event.edit(x)
    except KeyError:
        await event.edit(KeyError)

# TDK kütüphanesi ile bu şekilde.

# from tdk import tdk

# # create new word
# word = tdk.new_word("test")
# # prints meaning of the word
# test = "\n"
# for a in word.meaning():
#     test += "\n{}".format(a)
# # print(word.meaning())
# print(test)
# # # prints all the word's data
# # print(word.all_data())