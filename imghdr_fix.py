# Обходной путь для Python 3.13, где imghdr был удален
import sys

if sys.version_info >= (3, 13):
    # Эмуляция imghdr для Python 3.13
    import imghdr


    def imghdr_what(file, h=None):
        return imghdr.what(file)


    # Заменяем функцию what
    imghdr.what = imghdr_what