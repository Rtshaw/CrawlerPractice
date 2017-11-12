# encoding:UTF-8
import queue  # model為 pyinstaller
import lxml
import requests
import os
from bs4 import BeautifulSoup
import zipfile
from PIL import Image

print('comico漫畫下載\n作者：ishadows\n')
s = requests.Session()
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) \
                    AppleWebKit/537.36 (KHTML, like Gecko) \
                    Chrome/60.0.3112.90 Safari/537.36',
}

# 登入並保存正確的帳號訊息
flag = 1
while flag != None:
    if os.path.isfile('login.txt'):
        with open('login.txt', 'r') as f:
            loginid = f.readline().strip()
            password = f.readline().strip()
            # print(loginid,password)
    else:
        loginid = input('電子信箱：')
        password = input('密碼：')
    print('\n開始嘗試登入\n')
    data = {
        'autoLoginChk': 'Y',
        'loginid': loginid,
        'password': password,
        'nexturl': 'http://www.comico.com.tw/index.nhn',
    }
    r = s.post('https://id.comico.com.tw/login/login.nhn', data=data, headers=headers)
    r = s.get("https://id.comico.com.tw/login/login.nhn")

    soup = BeautifulSoup(r.text, 'lxml')
    # 若登入失敗，login.nhn返回一個js函數，成功便返回一個網頁
    flag = soup.find('body')
    if flag == None:
        with open('login.txt', 'w') as f:
            f.write('%s\n%s' % (loginid, password))
            print('登入成功\n')
    else:
        if os.path.isfile('login.txt'):
            os.remove('login.txt')
        print('登入失敗，請重試\n')

# 漫畫代碼，relife 的為 1
# titleNo = '1'
print ('以 relife為例，網址是：http://www.comico.com.tw/1/\n 網址最後為 1 即為此漫畫之漫畫代碼')
titleNo = int(input('漫畫代碼：'))
print('說明：\n以第186話為例，網址是：http://www.comico.com.tw/1/193/ \n網址最後的數字 193 即為這話的網頁代碼\n如果只下載一話，則 開始與結束 的網頁代碼都填這一話的即可\n')
b = int(input('開始網頁代碼:'))
e = int(input('結束網頁代碼:'))
while e < b:
    print('輸入錯誤！\n')
    b = int(input('開始網頁:'))
    e = int(input('結束網頁:'))

for n in range(b, e + 1):
    articleNo = str(n)
    r = s.get("http://www.comico.com.tw/%s/%d/" % (titleNo, n))
    soup = BeautifulSoup(r.text, 'lxml')

    # 檢查章節是否解鎖
    if soup.find(class_="locked-episode__list-btn-item") != None:
        pay_data = {
            'titleNo': titleNo,
            'articleNo': articleNo,
            'paymentCode': 'K',
            'coinUseToken': '',
            'productNo': '5',
            'price': '9',
            'rentalPrice': '',
        }
        pay_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) \AppleWebKit/537.36 (KHTML, like Gecko) \Chrome/60.0.3112.90 Safari/537.36',
            'DNT': '1',
            'Host': 'www.comico.com.tw',
            'Origin': 'http://www.comico.com.tw',
            'Pragma': 'no-cache',
            'Referer': 'http://www.comico.com.tw/%s/%d/' % (titleNo, n),
            'Upgrade-Insecure-Requests': '1',
        }
        s.post('http://www.comico.com.tw/consume/index.nhn', data=pay_data, headers=pay_headers)
        r = s.get('http://www.comico.com.tw/%s/%d/' % (titleNo, n), data=data, headers=headers)
        soup = BeautifulSoup(r.text, 'lxml')

    if soup.find(class_="locked-episode__list-btn-item") != None:
        print(' 《%s》 無法下載\n' % title)
        continue

    # 獲取標題
    title_div = soup.find(class_="comico-global-header__page-title-ellipsis")
    title = title_div.string
    # 去除最後的空格
    title.rstrip()
    # 避免半角問號導致資料夾無法命名
    title.replace('?', '？')
    title.replace('!', '！')

    # 檢查章節是否解鎖
    if soup.find(class_="locked-episode__list-btn-item") != None:
        print(soup.find(class_="locked-episode__list-btn-item"))
        print(' 《%s》 無法下載\n' % title)
        continue

    # 獲取圖片連結
    firstimg_div = soup.find(class_="comic-image__image")
    firstimg_url = firstimg_div.get('src')
    url = []
    url.append("%s" % firstimg_url)

    # 提取在js中的圖片連結
    items = soup.find_all('script', limit=3)
    string = str(items[2].string)
    string = string.replace(']', '[')
    string = string.split("[")
    string = string[1].replace("\r\n\t\r\n\t'", "'\r\n\t")
    string = string.replace("',\r\n\t'", "'\r\n\t")
    string = string.split("'\r\n\t")
    url.extend(string[1:-1])
    print('已獲取 《%s》 的下載連結' % title)

    # 建立資料夾
    imgdir = './%s' % title
    if os.path.isdir(imgdir) == False:
        os.mkdir(imgdir)

    # 建立壓縮文件
    zfile = zipfile.ZipFile("%s.zip" % title, "w", zipfile.zlib.DEFLATED)

    imgpath = []

    # 下載圖片並增加到壓縮文件中
    for i in url:
        path = '%s/%s' % (imgdir, i[-74:-68])
        imgpath.append(path)
        r = s.get(i, stream=True)
        if r.status_code == 200:
            with open(path, 'wb') as f:
                for chunk in r:
                    f.write(chunk)
            zfile.write(path, os.path.basename(path), zipfile.ZIP_DEFLATED)
    zfile.close()
    print('已完成 《%s》 的下載' % title)

    # 拼接長圖
    images = map(Image.open, imgpath)
    heights = [i.height for i in images]
    total_height = sum(heights)
    new_im = Image.new('RGB', (690, total_height))
    y_offset = 0
    for im in imgpath:
        fromImage = Image.open(im)
        new_im.paste(fromImage, (0, y_offset))
        fromImage.close()
        y_offset = y_offset + 2000
    new_im.save('%s.jpg' % title)
    print('已拼接長圖\n')
print('所有下載任務已經完成')
input('按任意鍵退出')
