# -*- coding: utf-8 -*-

# 引入必要套件
import cv2
import numpy
import pickle
from helpers import resize_to_fit
from keras.models import load_model

def noise_remove(image_path, threshold):
    """
    Remove noise
    :param image_path: Image's location
    :param threshold: Threshold
    """

    def calculate_noise_count(image_object, width, height):
        """        
        Calculate the number of areas that are not white
        :param image_object: Image Object
        :param width: Width
        :param height: Height
        """

        COUNT = 0
        WIDTH, HEIGHT = image_object.shape

        for __Width_ in [width-1, width, width+1]:
            for __Height_ in [height-1, height, height+1]:
                if __Width_ > WIDTH-1:
                    continue
                if __Height_ > HEIGHT-1:
                    continue
                if __Width_ == WIDTH and __Height_ == HEIGHT:
                    continue
                if image_object[__Width_, __Height_] < 185:
                    COUNT += 1
        return COUNT

    image = cv2.imread(image_path, 1)

    # 灰度
    image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    w, h = image_gray.shape
    for _w in range(w):
        for _h in range(h):
            if _w == 0 or _h == 0:
                image_gray[_w, _h] = 255
                continue
            # Calculate Pixel value < 255
            pixel = image_gray[_w, _h]
            if pixel == 255:
                continue

            if calculate_noise_count(image_gray, _w, _h) < threshold:
                image_gray[_w, _h] = 255

    _, image_gray = cv2.threshold(image_gray, 185, 255, cv2.THRESH_BINARY)

    cv2.imwrite(image_path, image_gray)
    return image_gray


def solve_captcha_with_models(captcha_path, model_path, number_length=4):
    """"預測驗證碼
    :param captcha_path: 驗證碼路徑
    :param model_path: 模型路徑
    :param number_length: 驗證碼長度
    """

    train_model = load_model(model_path)
    BatchSize = 1

    image = cv2.imread(captcha_path, 1)
    height, width = image.shape[:2]
    n_length, n_class = number_length, 10

    X = numpy.zeros((BatchSize, height, width, 3), dtype=numpy.uint8)

    for i in range(BatchSize):
        XTest = cv2.imread(captcha_path, 1)
        X[i] = XTest

    YPredict = train_model.predict(X)
    YPredict = numpy.argmax(YPredict, axis=2)

    Captcha = ''

    for i in range(BatchSize):
        print('驗證碼：', end='')
        print(''.join(map(str, YPredict[:, i].tolist())))
        Captcha = ''.join(map(str, YPredict[:, i].tolist()))

    return Captcha
