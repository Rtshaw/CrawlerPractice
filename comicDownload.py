# encoding:UTF-8
import lxml
import requests
import re
import sys
import os
import zipfile
from bs4 import BeautifulSoup
from PIL import Image

print('百合會漫畫下載\n作者：rtshaw\n')
s = requests.Session()

login_url = 'https://bbs.yamibo.com/member.php?mod=logging&action=login&infloat=yes&handlekey=login&inajax=1&ajaxtarget=fwin_content_login'
comic_url = 'https://bbs.yamibo.com/forum-30-1.html'

# 獲取登入loginhash
def get_login_window():
    url = login_url
    headers = {
        'Upgrade-Insecure-Requests':'1',
        'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    # 清空原haeaders
    s.headers.clear()
    # 更新headers
    s.headers.update(headers)
    r = s.get(url)
    # 獲取loginhash
    tmp = r.text.find('loginhash')+len('loginhash')+1
    loginhash = r.text[tmp:tmp+5]
    # print("loginhash = " + loginhash)
    return(loginhash)

loginhash = get_login_window()

# 登入並保存帳號
if os.path.isfile('account.txt'):
    with open('account.txt', 'r') as f:
        username = f.readline().strip()
        password = f.readline().strip()
else:
    username = input("帳號：")
    password = input("密碼：")
    with open('account.txt', 'w') as f:
        f.write('%s\n%s' %(username, password))
print("\n開始嘗試登入\n")

# 模擬登入
def login(loginhash, username, password):
    url = 'https://bbs.yamibo.com/member.php?mod=logging&action=login&loginsubmit=yes&loginhash='+loginhash+'&inajax=1'
    data = {
        'loginfield' : 'username',
        'username' : username,
        'password' : password,
        'questionid' : '0',
        'answer' : '',
        'referer' : 'https://bbs.yamibo.com/./'
    }
    headers = {
        'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Encoding':'gzip, deflate, br',
        'Accept-Language':'en-US,en;q=0.9,zh-TW;q=0.8,zh;q=0.7,ja;q=0.6,zh-CN;q=0.5',
        'Cache-Control':'max-age=0',
        'Connection':'keep-alive',
        'Content-Length':'146',
        'Content-Type':'application/x-www-form-urlencoded',
        'Host':'bbs.yamibo.com',
        'Origin':'https://bbs.yamibo.com',
        'Referer':'https://bbs.yamibo.com/member.php?mod=logging&action=login',
        'Upgrade-Insecure-Requests':'1',
        'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.84 Safari/537.36',
    }
    s.headers.clear()
    s.headers.update(headers)
    r = s.post(url, data)
    # print(r.text)

# 建立資料夾
def mkdir(comicName):
    if os.path.exists(comicName):
        print("\n%s 資料夾已存在，開始下一步\n" %comicName)
    else:
        os.mkdir(comicName)
        print("\n%s 資料夾創建成功\n" %comicName)

# 下載漫畫
def downloadcomic():
    login(loginhash, username, password)
    url = comic_url
    s.headers.clear()
    r = s.get(url)
    message = r.text.split('</title>')[0].split('<title>')[-1]
    # print(message)
    if(message == "中文百合漫画区 -  百合会 -  Powered by Discuz!"):
        print("登入成功\n")
    else:
        print("登入失敗，再試一次\n")
        sys.exit(0)
    
    soup = BeautifulSoup(r.text, "lxml")
    titleName = soup.find_all(class_= "s xst")

    # 要抓取漫畫的網頁代碼
    comicnum = int(input("要下載幾個頁面："))
    print("\n說明：\n以 https://bbs.yamibo.com/thread-475959-1-1.html 為例，475959 為網頁代碼。\n")
    titleNo = []
    for time in range(comicnum):
        titletmp = input("第 "+str(time+1)+" 個網頁代碼：")
        titleNo.append(titletmp)
        # print(titleNo[time])

    for down in range(comicnum):
        # print("\n排隊佇列："+str(titleNo))
        url = "https://bbs.yamibo.com/thread-%s-1-1.html" % titleNo.pop()
        r = s.get(url)
        soup = BeautifulSoup(r.text, "lxml")
        titleName = soup.find('title')
        # print(titleName.get_text())
        
        # 建立漫畫資料夾
        dirname = r.text.split("<meta name=\"description\"")[0].split("<meta name=\"keywords\" content=\"")[-1].split("\" />")[0]
        # print(dirname)
        mkdir(dirname)
               
        # 另外一種放在img標籤裡的抓法
        img_img = soup.find_all('img', 'zoom', lazyloadthumb='1')
        img_img_list = []
        
        for l in img_img:
            img_img_list.append(str(l)) # 轉成list
            # print(img_img_list)
        
        # 抓圖片連結並下載
        name = 1
        for i in img_img_list:
            img_url = i.split(" ")[4].split("\"")[1]
            # print(img_url)
            # print(type(img_img))
            name = str(name)
            
            if((".jpeg" in img_url) or (".jpg" in img_url) or (".JPG" in img_url) or ("png" in img_url)):
                    img_res = s.get(img_url)
                    img = img_res.content
                    filename = name+".jpg"
                    imgdir = ("%s/" %dirname)
                    filepath = imgdir+filename
                    fileout = open(filepath, "wb")
                    fileout.write(img)
                    print("%s, ...OK" %filename)
            
            name = int(name)
            name = name+1 
        
        # 下載圖片
        img = r.text.split("<ignore_js_op>")  # 大部分的漫畫可以從這個標籤爬到    
        for drink in img:
            line = drink.split("/>")[0]
            picname = drink.split("</p>")[0].split("</strong>")[0]
            # print(line)
            # print(type(img))
       
            # 獲取圖片連結
            if(("file" in line) and ("class=\"xs0\"" in picname)):
                img_file = line.split("file=\"")[-1].split("\"")[0]
                img_url = "https://bbs.yamibo.com/"+img_file
                # print(img_url)
                # print(filename)
                if((".jpeg" in img_url) or (".jpg" in img_url) or (".JPG" in img_url) or ("png" in img_url)):
                    img_res = s.get(img_url)
                    img = img_res.content
                    filename = picname.split("strong>")[-1]
                    imgdir = ("%s/" %dirname)
                    filepath = imgdir+filename
                    fileout = open(filepath, "wb")
                    fileout.write(img)
                    print("%s, ...OK" %filename)
                                 
       
        print("\n%s Done" %dirname)


    '''
    # 印出第一頁標題
    with open("thread.txt", "w") as f:
    for drink in title_name:
    f.write(drink.get_text())
    f.write('\n')
    print(drink.get_text())
    # 印出第一頁所有網址
    with open("href.txt", "w") as f:
    for drink in soup.find_all('a'):
    f.write(str(drink.get('href')))
    f.write('\n')
    # print(str(drink.get('href')))
    '''

downloadcomic()

