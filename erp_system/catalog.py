"""演示主数据；报价站共用物料编号，网页价格由报价站独立维护。"""

# 客户仅作为初始数据，新建销售单时也可填写其他客户名称。
CUSTOMERS = [
    {"id": 1, "name": "东江大学", "contact": "实验教学中心"},
    {"id": 2, "name": "远航科技有限公司", "contact": "设备采购部"},
    {"id": 3, "name": "江城建筑设计有限公司", "contact": "信息技术部"},
    {"id": 4, "name": "海岚职业技术学院", "contact": "实训中心"},
    {"id": 5, "name": "青禾数字传媒有限公司", "contact": "制作部"},
    {"id": 6, "name": "星越软件有限公司", "contact": "行政采购部"},
    {"id": 7, "name": "博睿自动化设备有限公司", "contact": "研发部"},
]

HISTORY_QUANTITIES = (10, 12, 15, 20, 12, 16)

SUPPLIERS = [
    {"id": 1, "code": "HX", "slug": "huaxin", "name": "华芯电子", "city": "深圳", "qualified": 1, "rating": "A", "lead_days": 3, "payment_terms": "到货后30天", "contact": "陈经理", "phone": "0755-00001001", "description": "笔记本核心器件与整机配套供应，支持小批量补料。"},
    {"id": 2, "code": "LC", "slug": "lianchuang", "name": "联创存储", "city": "苏州", "qualified": 1, "rating": "A", "lead_days": 5, "payment_terms": "到货后15天", "contact": "周经理", "phone": "0512-00001002", "description": "面向制造企业的批量采购渠道，提供阶梯报价。"},
    {"id": 3, "code": "YP", "slug": "yaoping", "name": "曜屏光电", "city": "东莞", "qualified": 1, "rating": "B", "lead_days": 1, "payment_terms": "到货付款", "contact": "刘经理", "phone": "0769-00001003", "description": "显示总成及笔记本零件现货配送，支持急单。"},
    {"id": 4, "code": "BY", "slug": "boyuan", "name": "博远工贸", "city": "广州", "qualified": 0, "rating": "待审核", "lead_days": 2, "payment_terms": "预付款", "contact": "赵经理", "phone": "020-00001004", "description": "电脑零部件综合贸易渠道，企业准入资料待审核。"},
]

# 单价为元；库存为件，内存为根，螺丝为颗。
PARTS = [
    {"id": 1, "code": "CPU-HX8", "name": "CPU", "model": "HX8-127H", "category": "计算核心", "specs": "移动级BGA处理器，8核16线程，集成显卡", "unit": "颗", "aliases": ["处理器", "CPU", "cpu"], "price": "1500.00", "bom_qty": 1, "stock": 20, "safety": 10},
    {"id": 2, "code": "RAM-D5-16", "name": "内存条", "model": "D5-SODIMM-16G-5600", "category": "存储", "specs": "DDR5 SO-DIMM，16GB，5600MT/s", "unit": "根", "aliases": ["内存", "RAM", "DDR5"], "price": "260.00", "bom_qty": 2, "stock": 300, "safety": 40},
    {"id": 3, "code": "SSD-NV-1T", "name": "固态硬盘", "model": "NV4-1TB-2280", "category": "存储", "specs": "M.2 2280，PCIe 4.0，1TB", "unit": "块", "aliases": ["SSD", "硬盘"], "price": "380.00", "bom_qty": 1, "stock": 140, "safety": 20},
    {"id": 4, "code": "LCD-16-QHD", "name": "屏幕总成", "model": "QHD16-165-EDP40", "category": "显示", "specs": "16英寸，2560×1600，165Hz，eDP 40针", "unit": "块", "aliases": ["屏幕", "显示屏", "LCD"], "price": "620.00", "bom_qty": 1, "stock": 10, "safety": 10},
    {"id": 5, "code": "PCB-HX8", "name": "主板", "model": "PCB-HX8-R1", "category": "主板", "specs": "HX8兼容裸板，含外围元件，不含CPU和内存", "unit": "块", "aliases": ["主板", "PCB"], "price": "520.00", "bom_qty": 1, "stock": 130, "safety": 15},
    {"id": 6, "code": "BAT-80WH", "name": "电池", "model": "BAT4S-80WH", "category": "机电", "specs": "4串锂电，80Wh，带保护板", "unit": "块", "aliases": ["电池"], "price": "220.00", "bom_qty": 1, "stock": 130, "safety": 15},
    {"id": 7, "code": "CASE-16-AL", "name": "机壳套件", "model": "AL16-ABCD", "category": "结构", "specs": "16英寸铝合金A/B/C/D壳套件", "unit": "套", "aliases": ["机壳", "外壳"], "price": "180.00", "bom_qty": 1, "stock": 130, "safety": 15},
    {"id": 8, "code": "KB-16-CN", "name": "键盘总成", "model": "KB16-CN-BL", "category": "外设", "specs": "中文背光键盘，含触控板", "unit": "套", "aliases": ["键盘", "触控板"], "price": "85.00", "bom_qty": 1, "stock": 130, "safety": 15},
    {"id": 9, "code": "COOL-DUAL", "name": "散热模组", "model": "DUAL-FAN-HX8", "category": "机电", "specs": "双风扇，双热管，HX8适配", "unit": "套", "aliases": ["散热", "风扇"], "price": "95.00", "bom_qty": 1, "stock": 130, "safety": 15},
    {"id": 10, "code": "PWR-100W", "name": "电源适配器", "model": "PD100-C", "category": "外设", "specs": "USB-C PD，100W，含电源线", "unit": "套", "aliases": ["充电器", "电源"], "price": "90.00", "bom_qty": 1, "stock": 130, "safety": 15},
    {"id": 11, "code": "SCREW-M2", "name": "螺丝", "model": "M2-MIX-16", "category": "结构", "specs": "M2混合规格，单颗计价", "unit": "颗", "aliases": ["螺丝", "紧固件"], "price": "0.50", "bom_qty": 30, "stock": 3600, "safety": 300},
    {"id": 12, "code": "PACK-16", "name": "包装套件", "model": "BOX16-EPE", "category": "包装", "specs": "纸箱、EPE内衬、标签及说明书", "unit": "套", "aliases": ["包装", "纸箱"], "price": "25.00", "bom_qty": 1, "stock": 130, "safety": 15},
]
