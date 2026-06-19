"""legacy 模块唯一收容目录，禁止散落。

所有 ``legacy_*`` 命名的过渡期模块必须迁入此目录；禁止在 ``app/`` 其他子目录
新增 ``legacy_*`` 文件。``scripts/arch_fitness.py`` 的 ``check_legacy_boundary``
会扫描 ``app/`` 下所有 ``legacy_*.py``，凡不在 ``app/legacy/`` 下的均记为违规。

迁入登记见本目录 ``README.md``。每个 legacy 模块须标注退役条件，退役后从本目录删除。
"""
