# -*- coding: utf-8 -*-

# 引入必要套件
import cv2
import numpy
import pickle
from helpers import resize_to_fit
from keras.models import load_model


def solve_captcha_with_models(captcha_path, model_path, model_labels_path):
    """預測驗證碼
    :param captcha_path: 驗證碼路徑
    :param model_path: 模型路徑
    :param model_labels_path: Label路徑
    """

    with open(model_labels_path, "rb") as f:
        lb = pickle.load(f)

    Model = load_model(model_path)

    Image = cv2.imread(captcha_path)
    Image = cv2.cvtColor(Image, cv2.COLOR_BGR2GRAY)

    # 二值化
    _, Image = cv2.threshold(Image, 185, 255, cv2.THRESH_BINARY)

    Image = cv2.copyMakeBorder(Image, 20, 20, 20, 20, cv2.BORDER_REPLICATE)

    Thresh = cv2.threshold(
        Image, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    Contours = cv2.findContours(
        Thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    Contours = Contours[0]

    LetterImageRegions = []

    for Contour in Contours:
        (x, y, w, h) = cv2.boundingRect(Contour)

        if w / h > 1.25:
            half_width = int(w / 2)
            LetterImageRegions.append((x, y, half_width, h))
            LetterImageRegions.append((x + half_width, y, half_width, h))
        else:
            LetterImageRegions.append((x, y, w, h))

    LetterImageRegions = sorted(LetterImageRegions, key=lambda x: x[0])

    Output = cv2.merge([Image] * 3)
    Predictions = []

    for LetterBoundingBox in LetterImageRegions:
        x, y, w, h = LetterBoundingBox

        LetterImage = Image[y - 2:y + h + 2, x - 2:x + w + 2]

        LetterImage = resize_to_fit(LetterImage, 20, 20)

        if LetterImage is False:
            return False

        LetterImage = numpy.expand_dims(LetterImage, axis=2)
        LetterImage = numpy.expand_dims(LetterImage, axis=0)

        Prediction = Model.predict(LetterImage)

        Letter = lb.inverse_transform(Prediction)[0]
        Predictions.append(Letter)

        cv2.rectangle(Output, (x - 2, y - 2),
                      (x + w + 4, y + h + 4), (0, 255, 0), 1)
        cv2.putText(Output, Letter, (x - 5, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

    CaptchaText = "".join(Predictions)
    print("驗證碼：{}".format(CaptchaText))

    print(len(CaptchaText))

    return CaptchaText
