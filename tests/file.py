'''
file（File 抽象）功能测试

纯单元测试：在测试进程里直接构造 `File`，覆盖三种构造签名、
`path` / `name` / `data` / `data_in_file` 取值、惰性读取，以及 `save(...)` 的各种组合。
临时文件都放在 `/tmp`，不污染仓库。
'''
import shutil
from pathlib import Path

from CheeseAPI.file import File

APP = 'apps/file.py'

ROOT = Path('/tmp/cheeseapi_file_test')

def workspace(name: str) -> Path:
    ''' 每个用例一个干净目录 '''
    path = ROOT / name
    shutil.rmtree(path, ignore_errors = True)
    path.mkdir(parents = True, exist_ok = True)
    return path

def write(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path

#### 三种构造签名 ####

def case_path_constructor_lazy(t, server):
    ''' `File(path)` 默认 data_in_file=True：不在构造时读文件，`data` 每次从磁盘读取 '''
    directory = workspace('path_lazy')
    source = write(directory / 'lazy.txt', b'first-content')

    file = File(str(source))

    t.check('File(path)：path 为传入路径', file.path == str(source), repr(file.path))
    t.check('File(path)：name 取路径末段', file.name == 'lazy.txt', repr(file.name))
    t.check('File(path)：data_in_file 为 True', file.data_in_file is True, repr(file.data_in_file))
    t.check('File(path)：构造时不读文件（_data 仍为 None）', file._data is None, repr(file._data))
    t.check('File(path)：data 首次读取得到磁盘内容', file.data == b'first-content', repr(file.data))

    write(source, b'second-content')
    t.check('File(path)：data 惰性读取，文件变化后返回新内容', file.data == b'second-content', repr(file.data))

def case_path_constructor_in_memory(t, server):
    ''' `File(path, data_in_file=False)`：构造时把内容读进内存，之后与磁盘变化解耦 '''
    directory = workspace('path_memory')
    source = write(directory / 'snapshot.txt', b'original')

    file = File(str(source), data_in_file = False)

    t.check('File(path, data_in_file=False)：data_in_file 为 False', file.data_in_file is False, repr(file.data_in_file))
    t.check('File(path, data_in_file=False)：构造时已读入内存', file._data == b'original', repr(file._data))
    t.check('File(path, data_in_file=False)：data 返回内存快照', file.data == b'original', repr(file.data))

    write(source, b'modified')
    t.check('File(path, data_in_file=False)：磁盘改动不影响已读入的数据', file.data == b'original', repr(file.data))

def case_memory_constructor(t, server):
    ''' `File(name, data)`：内存文件，path 为 None '''
    file = File('memory.txt', b'memory-bytes')

    t.check('File(name, data)：path 为 None', file.path is None, repr(file.path))
    t.check('File(name, data)：name 为传入名字', file.name == 'memory.txt', repr(file.name))
    t.check('File(name, data)：data 直接返回内存数据', file.data == b'memory-bytes', repr(file.data))

    # 实测：2 参构造不修改 data_in_file 标志，默认仍是 True，尽管数据其实在内存里（见下方已知缺陷）
    t.check('File(name, data)：实测 data_in_file 默认为 True', file.data_in_file is True, repr(file.data_in_file))
    t.check('File(name, data)：数据实际存在内存（_data 非 None）', file._data == b'memory-bytes', repr(file._data))

def case_memory_constructor_data_in_file_flag(t, server):
    '''
    `File(name, data)` 的 `data_in_file` 语义：数据在内存中，却报告 True

    框架内部用 `_data is None` 表示「数据在文件里」，而 2 参构造的 `_data` 非空，
    两者矛盾，调用方若按 `data_in_file` 判断会误以为数据已落盘。
    '''
    file = File('flag.txt', b'payload')

    t.known_issue(
        'File(name, data)：data_in_file 应表示数据不在文件中（False）',
        file.data_in_file is False,
        f'data_in_file={file.data_in_file!r}，但 _data={file._data!r} 说明数据在内存'
    )

def case_name_derivation(t, server):
    ''' `name` 取路径末段；data_in_file=True 时不需要路径真实存在 '''
    file = File('/tmp/cheeseapi_file_test/not/created/archive.tar.gz')

    t.check('File(path)：name 取最后一段（含扩展名）', file.name == 'archive.tar.gz', repr(file.name))
    t.check('File(path)：data_in_file=True 时不访问磁盘，不存在的路径也能构造', file.path == '/tmp/cheeseapi_file_test/not/created/archive.tar.gz', repr(file.path))

#### save ####

def case_save_from_memory(t, server):
    ''' 内存文件 save：内容落盘；update_path / data_in_file 的组合效果 '''
    directory = workspace('save_memory')
    target = directory / 'out.txt'

    file = File('mem.txt', b'saved-bytes')
    file.save(str(target))

    t.check('save：文件真的落盘', target.exists(), str(target))
    t.check('save：落盘内容与内存数据一致', target.read_bytes() == b'saved-bytes', repr(target.read_bytes()) if target.exists() else 'missing')
    t.check('save：update_path=False 时 path 不变', file.path is None, repr(file.path))
    t.check('save：默认 data_in_file=False，数据回到内存', file.data_in_file is False and file._data == b'saved-bytes', f'data_in_file={file.data_in_file!r}, _data={file._data!r}')

    second = directory / 'out2.txt'
    file.save(str(second), update_path = True, data_in_file = True)

    t.check('save(update_path=True)：path 更新为保存路径', file.path == str(second), repr(file.path))
    t.check('save(data_in_file=True)：_data 清空，改为按路径读取', file._data is None and file.data_in_file is True, f'_data={file._data!r}, data_in_file={file.data_in_file!r}')

    write(second, b'overwritten-later')
    t.check('save(data_in_file=True)：之后 data 反映磁盘的最新内容', file.data == b'overwritten-later', repr(file.data))

def case_save_from_path(t, server):
    ''' 路径文件 save：走复制路径，源文件保留；update_path 决定 path 指向 '''
    directory = workspace('save_path')
    source = write(directory / 'src.txt', b'source-content')

    file = File(str(source))
    target = directory / 'copy.txt'
    file.save(str(target))

    t.check('save（路径来源）：目标文件落盘且内容一致', target.exists() and target.read_bytes() == b'source-content', f'exists={target.exists()}')
    t.check('save（路径来源）：update_path=False 时仍指向源文件', file.path == str(source), repr(file.path))
    t.check('save（路径来源）：源文件未被移动或删除', source.read_bytes() == b'source-content', repr(source.read_bytes()))
    t.check('save（路径来源）：默认 data_in_file=False 时数据读回内存', file.data_in_file is False and file.data == b'source-content', f'data_in_file={file.data_in_file!r}, data={file.data!r}')

    target2 = directory / 'copy2.txt'
    other = File(str(source))
    other.save(str(target2), update_path = True)

    t.check('save（路径来源，update_path=True）：path 指向新文件', other.path == str(target2), repr(other.path))
    t.check('save（路径来源，update_path=True）：新文件内容正确', Path(other.path).read_bytes() == b'source-content', repr(Path(other.path).read_bytes()))

def case_save_path_mode_stays_lazy(t, server):
    ''' `data_in_file=True` 的路径文件 save 后依然保持惰性（不把整文件读进内存） '''
    directory = workspace('save_lazy')
    source = write(directory / 'big.txt', b'abcdefghij')

    file = File(str(source))
    target = directory / 'copy.txt'
    file.save(str(target), data_in_file = True)

    t.check('save(data_in_file=True)：_data 保持 None（惰性）', file._data is None and file.data_in_file is True, f'_data={file._data!r}, data_in_file={file.data_in_file!r}')
    t.check('save(data_in_file=True)：按路径读取内容正确', file.data == b'abcdefghij', repr(file.data))

def case_empty_memory_data(t, server):
    '''
    空的内存文件：`File(name, b'')` 的 `data` 应返回空字节

    实测 `data` 用 `if self._data:` 判空，空 bytes 会被当作「未加载」，
    于是去 `open(self._path)`，而内存文件 path 为 None，抛 TypeError。
    '''
    file = File('empty.txt', b'')

    t.check('File(name, b"")：构造成功且 name 正确', file.name == 'empty.txt' and file.path is None, f'name={file.name!r}, path={file.path!r}')

    try:
        data = file.data
        error = ''
    except Exception as e:
        data = None
        error = f'{type(e).__name__}: {e}'

    t.known_issue(
        'File(name, b"")：data 返回空字节',
        data == b'',
        f'data={data!r}，抛出 {error}（path 为 None 时被当成需要读文件）' if error else f'data={data!r}'
    )

def case_empty_path_file(t, server):
    ''' 空文件（路径来源）可以正常读取与保存 '''
    directory = workspace('empty_path')
    source = write(directory / 'empty.txt', b'')

    file = File(str(source))
    t.check('File(path)（空文件）：data 返回空字节', file.data == b'', repr(file.data))

    target = directory / 'empty-copy.txt'
    file.save(str(target), data_in_file = False)
    t.check('save（空文件）：目标存在且为空', target.exists() and target.read_bytes() == b'', f'exists={target.exists()}, size={target.stat().st_size if target.exists() else None}')

CASES = [
    ('File(path) 惰性读取', case_path_constructor_lazy),
    ('File(path, data_in_file=False) 内存快照', case_path_constructor_in_memory),
    ('File(name, data) 内存文件', case_memory_constructor),
    ('File(name, data) 的 data_in_file 标志', case_memory_constructor_data_in_file_flag),
    ('name 与 path 取值', case_name_derivation),
    ('save：内存文件落盘', case_save_from_memory),
    ('save：路径文件复制', case_save_from_path),
    ('save：保持惰性', case_save_path_mode_stays_lazy),
    ('空的内存文件', case_empty_memory_data),
    ('空的路径文件', case_empty_path_file)
]
