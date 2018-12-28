# -*- coding: utf-8 -*-
import sys
import getopt
import os
import time

import requests
from bs4 import BeautifulSoup
import multi_thread
import web_t

def thread_get(headers):
    global mutex, manga_list
    while True:
        if mutex.acquire():
            if len(manga_list) > 0:
                url = manga_list[0]
                del manga_list[0]
                mutex.release()
                # if dirname_g is None:
                dirname = 'D:\\devs\\python\\img'
                name = url.split('/')[-1].split('?')[0]
                if name.find('.') == -1:
                    name += '.jpg'
                filename = os.path.join(dirname, name)
                web_t.get_as_img(url, headers=headers, name=filename)
                # else:
                #     web_t.get_as_img(url, dirname=dirname_g, headers=headers)
                #print "%s: , Remain: %s" %(threading.currentThread().getName(), len(manga_list))
                time.sleep(1)
            else:
                mutex.release()
                time.sleep(1)
                return

def main(argv):
    #cycomics('2198', 2, 3, 4)
    #cycomics -i <chapter id> -b <begin page> -e <end page> -t <thread number> -o <output directory>
    ids = None
    begin = None
    end = None
    thread = None
    dirname = None
    try:
        opts, args = getopt.getopt(argv, "hi:b:e:t:o:")
    except getopt.GetoptError:
        print 'Illegal input\ncycomics -i <chapter id> [[-b <begin page> -e <end page>],\
         -t <thread number>, -o <output directory>] -h <help>'
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print 'cycomics -i <chapter id> [[-b <begin page> -e <end page>],\
             -t <thread number>, -o <output directory>] -h <help>'
            sys.exit()
        elif opt == "-i":
            ids = arg
        elif opt == "-b":
            begin = arg
        elif opt == "-e":
            end = arg
        elif opt == "-t":
            thread = arg
        elif opt == "-o":
            dirname = arg
    try:
        if ids is None or not ids.isdigit():
            raise Exception("chapter id")
        if begin is not None:
            if not begin.isdigit():
                raise Exception("begin page")
            else:
                begin = int(begin)
                if begin < 0:
                    raise Exception("'%s'page out of range" % begin)
        if end is not None:
            if not end.isdigit():
                raise Exception("end page")
            else:
                end = int(end)
                if end < 0:
                    raise Exception("'%s'page out of range" % end)
        if thread is not None:
            if not thread.isdigit():
                raise Exception("thread number")
            else:
                thread = int(thread)
                if thread < 1 or thread > 30:
                    raise Exception("thread number '%s' out of range" % thread)
        if dirname is not None and not os.path.isdir(dirname):
            raise Exception("output directory")

    except Exception, e:
        print 'Illegal input: ' + e.message
    else:
        cycomics(ids, begin, end, thread, dirname)

def pget():
    headers = {
        'User-Agent':
        'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36'
        ,'Referer':'https://comic.pixiv.net/viewer/stories/19683'
    }

    url = 'https://img-comic.pximg.net/c!/q=50,f=webp%3Ajpeg/images/page/19683/ABTTkvslSexDX8kLh3SH/2.jpg?20161222163844'
    web_t.get_as_img(url, headers, name='1.jpg')

def pcomic(p_id):
    headers = {
        'User-Agent':
        'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36'
        ,'Cookie':''
    }
    #Cookie is necessary

    url = 'https://comic.pixiv.net/viewer/stories/%s' % (p_id)
    # soup = web_t.get_soup(url, headers)
    s = requests.Session()
    r = s.get(url, headers=headers)
    soup = BeautifulSoup(r.content, "html.parser")
    jsonurl = soup.find('meta', attrs={"name":'viewer-api-url'})['content']
    token = soup.find('meta', attrs={"name":'csrf-token'})['content']
    if jsonurl is None or token is None:
        print "Page analysis error"
        return False
    if jsonurl == '':
        # when the 'viewer-api-url' is null,try to get json in this way
        jsonurl = '/api/v1/viewer/stories/myyGantMHb/%s.json' % (p_id)
    jsonurl = 'https://comic.pixiv.net' + jsonurl
    print jsonurl
    print token
    headers['Referer'] = url
    headers['X-CSRF-Token'] = token
    headers['X-Requested-With'] = 'XMLHttpRequest'
    res = s.get(jsonurl, headers=headers)
    json = res.json()
    # print json
    print 'If json response is error, check the cookie is updated'
    pages = json['data']['contents'][0]['pages']
    global manga_list
    manga_list = []
    for i in pages:
        if 'left' in i:
            purl = i['left']['data']['url']
            # print purl
            manga_list.append(purl)
        if 'right' in i:
            purl = i['right']['data']['url']
            # print purl
            manga_list.append(purl)
    headers2 = {
        'User-Agent':
        'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 Safari/537.36'
    }
    headers2['Referer'] = url
    global mutex
    mutex = multi_thread.threading.Lock()
    multi_thread.my_thread(thread_get, 5, (headers2,))
    return True

if __name__ == "__main__":
    # main(sys.argv[1:])
    pcomic(23987)