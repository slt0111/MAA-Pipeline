# -*- coding: utf-8 -*-
# PyInstaller 版本信息文件：决定 exe 右键属性里的产品名、版本等。
# 注意：本文件会被 PyInstaller 用 eval() 求值，因此只能有一个表达式，
# 不能出现模块级 docstring（那会成为第二个表达式导致 SyntaxError）。

VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(1, 4, 0, 0),
        prodvers=(1, 4, 0, 0),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "080404b0",
                    [
                        StringStruct("CompanyName", "MAA-Pipeline"),
                        StringStruct("FileDescription", "MAA 一键挂机助手"),
                        StringStruct("FileVersion", "1.4.0.0"),
                        StringStruct("InternalName", "MAA挂机助手"),
                        StringStruct("LegalCopyright", ""),
                        StringStruct("OriginalFilename", "MAA挂机助手.exe"),
                        StringStruct("ProductName", "MAA 一键挂机"),
                        StringStruct("ProductVersion", "1.4.0.0"),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [2052, 1200])]),
    ],
)
