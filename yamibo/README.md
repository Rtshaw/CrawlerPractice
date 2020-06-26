# yamibo
Can use it to download 300 comic.

### 安裝中文轉換
```
$ git clone https://github.com/yichen0831/opencc-python.git opencc
$ cd opencc
```

### 修改檔案內容
```
31 CONFIG_DIR = './opencc/opencc/config'
32 DICT_DIR = './opencc/opencc/dictionary'


105 # config_file = os.path.join(os.path.dirname(__file__), CONFIG_DIR, config)
106 config_file = CONFIG_DIR + '/' + config


164 # dict_file = os.path.join(os.path.dirname(__file__), DICT_DIR, filename)
165 dict_file = DICT_DIR + '/' + filename
```