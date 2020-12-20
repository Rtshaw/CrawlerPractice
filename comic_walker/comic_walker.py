# -*- coding: utf-8 -*-

__author__ = 'Riley'
__date__ = '2020/12/19'
__version__ = '0.0.1'

import re
import os
import json
import requests

from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup

session = requests.Session()
pre_url = 'https://comic-walker.com/'
headers = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36'
}
work_directory = os.getcwd()

def mkdir(comic_title: str, episode_title: str):
    """創建資料夾
    :param comic_title: 漫畫名稱
    :param episode_title: 章節名稱
    """

    if os.path.exists(work_directory+'\\Comic\\'):
        if os.path.exists(work_directory + f'\\Comic\\{comic_title}'):
            print(f'{comic_title} 資料夾已存在，進行下一步。')
            if os.path.exists(work_directory + f'\\Comic\\{comic_title}\\{episode_title}'):
                print(f'{episode_title} 資料夾已存在，開始下載漫畫\n')
            else:
                os.makedirs(work_directory + f'\\Comic\\{comic_title}\\{episode_title}')
                print(f'{comic_title} 資料夾，創建完成，開始下載漫畫\n')
        else:
            os.makedirs(work_directory + f'\\Comic\\{comic_title}\\{episode_title}')
            print(f'{comic_title}、{episode_title} 資料夾，創建完成，開始下載漫畫\n')
    else:
        os.makedirs(work_directory + f'\\Comic\\{comic_title}\\{episode_title}')
        print(f'漫畫資料夾、{comic_title}、{episode_title} 資料夾，創建完成，開始下載漫畫\n')

def choose_episode(prepare:str, download_urls: list):
    """選擇下載章節
    :param prepare: 欲下載章節
    :param download_urls: 章節 URL列表
    """
    result = []
    prepare = prepare.split('.')
    for pre_ in prepare:
        url = pre_url + download_urls[int(pre_)-1]
        parameters = urlparse(url)
        episode_id = parse_qs(parameters.query)['cid'][0]
        # 章節ID
        result.append(episode_id)
    
    return result

def download_comic(comic_id: str):
    """下載漫畫
    :param comic_id: 漫畫ID
    """
    # 進入漫畫頁面頁面
    url = f'https://comic-walker.com/jp/contents/detail/{comic_id}'
    response = session.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'lxml')

    try:
        ulreversible = soup.find(id='ulreversible')
        episodes = ulreversible.find_all('a')
    except Exception as e:
        print('請檢查下漫畫代碼')
        return {'message': e, 'type': 'no_find_all'}
    
    download_urls = []
    for index, episode in enumerate(episodes):
        download_urls.append(episode.get('href'))
        print(f'Episode {index+1}: ', episode.get('title'))
    
    prepare = input('\n輸入欲下載章節，數字以「.」區隔：')

    try:
        page_list = choose_episode(prepare, download_urls)
        for episode_id in page_list:
            get_comic_page(episode_id)
    except Exception as e:
        print('存在無效字元')
        return {'message': e, 'type': 'prepare_param_error'}

    return {'message': 'success', 'type': 'no_error'}
        
def generate_key(drm_hash: str):
    """cw-viewer.min.js generateKey
    :param source_url: 圖檔 url
    :param drm_hash: 圖檔 hash
    """
    temp = int(drm_hash[:16], 16)
    key = [int((temp>>i*8)%256) for i in range(8)][::-1]
    return key

def xor_image(image_list: list, drm_hash):
    """互斥
    :param image_list: 圖檔 list
    :param drm_hash: 圖檔 hash
    """
    key_list = generate_key(drm_hash)
    img_ = []
    for index in range(len(image_list)):
        img_.append(image_list[index] ^ key_list[index%8])
    return img_

def get_comic_page(episode_id: str):
    """漫畫頁面
    :param episode_id: 章節ID
    """
    # 取得頁面基本資訊
    url = f'https://comic-walker.com/viewer/?tw=2&dlcl=ja&cid={episode_id}'
    response = session.get(url, headers=headers)
    data_layer = json.loads(re.search('dataLayer = .*}];', response.text).group().split(' = ')[1].replace(';', '').strip("'<>() ").replace('\'', '\"'))[0]
    comic_title = data_layer['content_title'] # 漫畫標題
    episode_title = data_layer['episode_title'] # 章節標題
    mkdir(comic_title, episode_title) # 創建資料夾

    # 取得該章節圖片資訊
    url = f'https://comicwalker-api.nicomanga.jp/api/v1/comicwalker/episodes/{episode_id}/frames'
    response = session.get(url, headers=headers)
    raw_data = response.json()

    images_data = raw_data['data']['result']

    for index, image in enumerate(images_data):
        # print(image)
        source_url = image['meta']['source_url'] # 圖檔路徑
        drm_hash = image['meta']['drm_hash'] # hash參數

        response = session.get(source_url, stream=True, timeout=30)
        image = xor_image(response.content, drm_hash)

        with open(work_directory + f'\\Comic\\{comic_title}\\{episode_title}\\{index+1}.jpg', 'wb') as w:
            for data_image in image:
                w.write((data_image).to_bytes(length=1, byteorder='big'))
            print(f'{episode_title} . {index}.jpg, ...OK ')

if __name__ == "__main__":

    print('ComicWalker 下載\n作者：Riley')
    print("\n說明：\n以 https://comic-walker.com/jp/contents/detail/KDCW_AM05200995010000_68 為例，KDCW_AM05200995010000_68 為漫畫代碼。\n")

    comic_id = input('請輸入漫畫代碼：')
    response = download_comic(comic_id)

    while response['message'] != 'success':
        if response['type'] == 'no_find_all':
            comic_id = input('請輸入漫畫代碼：')
        response = download_comic(comic_id)