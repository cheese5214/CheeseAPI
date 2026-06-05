import shutil
from typing import overload

class File:
    __slots__ = ('_path', '_name', '_data_in_file', '_data')

    @overload
    def __init__(self, path: str, *, data_in_file: bool = True):
        '''
        - Args
            - data_in_file: 是否将数据保存在文件中，若否则读取文件内容到内存
        '''

    @overload
    def __init__(self, name: str, data: bytes):
        ...

    def __init__(self, *args, data_in_file: bool = True):
        self._path: str | None = None
        self._name: str
        self._data_in_file: bool = data_in_file
        self._data: bytes | None = None
        if len(args) == 1:
            self._path = args[0]
            self._name = self._path.split('/')[-1]
            if self.data_in_file is False:
                with open(self._path, 'rb') as f:
                    self._data = f.read()
        elif len(args) == 2:
            self._name = args[0]
            self._data = args[1]

    def save(self, path: str, update_path: bool = False, data_in_file: bool = False):
        '''
        - Args
            - update_path: 是否更新文件路径为保存后的路径
            - data_in_file: 是否将数据保存在文件中，若否则读取文件内容到内存
        '''

        if self._data is not None:
            with open(path, 'wb') as f:
                f.write(self.data)
        else:
            shutil.copyfile(self.path, path)

        if update_path:
            self._path = path

        if data_in_file:
            self._data = None
        else:
            with open(path, 'rb') as f:
                self._data = f.read()
        self._data_in_file = data_in_file

    @property
    def path(self) -> str | None:
        return self._path

    @property
    def data_in_file(self) -> bool:
        ''' 是否将数据保存在文件中，若否则读取文件内容到内存 '''

        return self._data_in_file

    @property
    def data(self) -> bytes:
        if self._data:
            return self._data
        else:
            with open(self._path, 'rb') as f:
                return f.read()

    @property
    def name(self) -> str:
        return self._name
