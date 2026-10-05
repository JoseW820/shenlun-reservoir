# -*- coding: utf-8 -*-
"""gk_core 纯函数与索引层的回归测试。

测试用例大多来自代码注释里的实测校准样本 —— 改正则/阈值前跑一遍，
防止「看起来对但机制错」的回归。
"""
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gk_core as gk                      # noqa: E402
import weekly_digest as wk                # noqa: E402  （junk/graphic 判定在 CLI 侧）

TF = {
    'hardBlock': ['升国旗', '完胜', '夺冠', '招标公告', '人事任免'],
    'softBlock': ['座谈会', '事故', '表彰', '会见'],
    'policySignals': ['部署', '意见', '治理', '规划'],
}


# ---------------------------------------------------------------- URL 指纹

class TestNormUrl:
    def test_unify_scheme_host_case(self):
        assert gk.norm_url('HTTP://WWW.Example.COM/a/b') == 'https://example.com/a/b'

    def test_strip_anchor_and_tracking(self):
        assert (gk.norm_url('https://www.gov.cn/x/?utm_source=foo&id=3#top')
                == 'https://gov.cn/x/?id=3')

    def test_trailing_slash(self):
        assert gk.norm_url('https://example.com/a/') == 'https://example.com/a'
        assert gk.norm_url('http://example.com') == 'https://example.com/'

    def test_empty(self):
        assert gk.norm_url('') == ''
        assert gk.norm_url(None) == ''

    def test_same_page_http_https(self):
        assert gk.norm_url('http://gov.cn/a') == gk.norm_url('https://gov.cn/a')


# --------------------------------------------------------------- 标题指纹

class TestNormTitle:
    def test_strip_source_suffix(self):
        assert gk.norm_title('习近平出席欢迎宴会- 求是网') == gk.norm_title('习近平出席欢迎宴会')

    def test_strip_column_suffix(self):
        assert gk.norm_title('国务院关于优化营商环境的意见_政策解读') == \
               gk.norm_title('国务院关于优化营商环境的意见')

    def test_strip_decor_parens(self):
        assert gk.norm_title('某地调研（组图）') == gk.norm_title('某地调研')

    def test_form_head_tail_normalized(self):
        """一图读懂《X》与《X》全文 应归一化为同一指纹。"""
        a = gk.norm_title('一图读懂《轻工业数字化转型实施方案》')
        b = gk.norm_title('《轻工业数字化转型实施方案》全文')
        assert a == b

    def test_punctuation_removed(self):
        assert gk.norm_title('乡村振兴：产业兴旺！') == gk.norm_title('乡村振兴产业兴旺')

    def test_empty(self):
        assert gk.norm_title('') == ''


# --------------------------------------------------------------- 通稿过滤

class TestTitleBlocked:
    def test_hard_block(self):
        assert gk.title_blocked('今晨举行升国旗仪式', TF)[0] is True
        assert gk.title_blocked('中国男排完胜泰国队', TF)[0] is True

    def test_soft_block_without_signal(self):
        assert gk.title_blocked('某某座谈会今日召开', TF)[0] is True

    def test_soft_block_with_signal_kept(self):
        assert gk.title_blocked('防汛工作座谈会部署下一步任务', TF)[0] is False

    def test_meeting_not_blocked(self):
        """「会议」刻意不在黑名单 —— 国常会部署是核心素材。"""
        assert gk.title_blocked('国务院常务会议部署稳增长一揽子措施', TF)[0] is False


# ------------------------------------------------------------------- 摘要

class TestMakeSummary:
    def test_strip_script_style(self):
        html = '<style>body{color:red}</style><script>var x=1</script><p>正文内容在这里。</p>'
        s = gk.make_summary(html, 110, 20000)
        assert 'color' not in s and 'var x' not in s and '正文内容' in s

    def test_strip_dateline(self):
        html = '新华社北京9月30日电 题：乡村振兴的新路径　某地通过发展特色产业实现增收。'
        s = gk.make_summary(html, 110, 20000)
        assert not s.startswith('新华社')

    def test_strip_inline_signature(self):
        html = '某地推进改革。（记者张三）改革内容包括多个方面，取得了显著成效。'
        s = gk.make_summary(html, 110, 20000)
        assert '记者' not in s

    def test_collapse_adjacent_repeat(self):
        seg = '这是一段超过十个字的导语内容。'
        s = gk.make_summary(seg + seg + '后续正文继续展开论述。', 110, 20000)
        assert s.count('导语内容') == 1

    def test_length_cap(self):
        html = '长' * 500 + '。'
        s = gk.make_summary(html, 110, 20000)
        assert len(s) <= 111      # limit 或 limit + 省略号


# --------------------------------------------------------------- 模糊判重
# 用例来自 FUZZY_THRESHOLD 的实测校准注释。

class TestFuzzyDedup:
    def test_prefix_variant_should_merge(self):
        """0.889 档：前缀增补的同一篇，应判重。"""
        a = gk.norm_title('乡村行 看振兴丨智能农机上阵 山西大同趁墒播种赶农时')
        b = gk.norm_title('智能农机上阵 山西大同趁墒播种赶农时')
        assert gk.title_similarity(a, b) >= gk.FUZZY_THRESHOLD

    def test_different_orgs_should_not_merge(self):
        """0.733 档：不同机构各自发的同模板稿，不是同一篇。"""
        c = gk.norm_title('国家粮食和物资储备局：扎实做好 2025 年秋粮收购工作')
        d = gk.norm_title('黑龙江省发改委：扎实做好 2025 年秋粮收购工作')
        assert gk.title_similarity(c, d) < gk.FUZZY_THRESHOLD

    def test_word_order_variant_should_merge(self):
        """0.786 档：语序微调的同一篇，应判重。"""
        a = gk.norm_title('如何发挥企业在基础研究中的作用')
        b = gk.norm_title('发挥企业在基础研究中的重要作用')
        assert gk.title_similarity(a, b) >= gk.FUZZY_THRESHOLD

    def test_digits_veto(self):
        """8月发布会 vs 7月发布会：再像也是不同事件。"""
        assert gk.digits_compatible(('8',), ('7',)) is False
        assert gk.digits_compatible(('2025',), ('2025',)) is True
        assert gk.digits_compatible((), ('1',)) is True

    def test_lookup_integration(self):
        known = {'grams': {}, 'items': []}
        fp_a = gk.norm_title('智能农机上阵 山西大同趁墒播种赶农时')
        gk.fuzzy_add(known, fp_a, gk.title_digits('智能农机上阵 山西大同趁墒播种赶农时'),
                     {'nurl': 'https://a/1', 'title': 'A'})
        fp_b = gk.norm_title('乡村行 看振兴丨智能农机上阵 山西大同趁墒播种赶农时')
        hit = gk.fuzzy_lookup(known, fp_b,
                              gk.title_digits('乡村行 看振兴丨智能农机上阵 山西大同趁墒播种赶农时'),
                              skip_nurl='https://b/2')
        assert hit is not None and hit['nurl'] == 'https://a/1'


# ----------------------------------------------------------- 索引层（内存库）

def _mem_db():
    con = sqlite3.connect(':memory:')
    con.executescript(gk.INDEX_SCHEMA)
    return con


def _row(nurl, title, source_id, days_old, typ='案例型'):
    d = datetime.now(timezone.utc) - timedelta(days=days_old)
    return {'nurl': nurl, 'ntitle': gk.norm_title(title), 'title': title,
            'url': nurl, 'source_id': source_id, 'source': source_id,
            'type': typ, 'date': d, 'summary': '', 'collection': ''}


class TestIndex:
    def test_insert_idempotent(self):
        con = _mem_db()
        rows = [_row('https://a/1', '某省推进乡村振兴的调研报道', 's1', 1)]
        assert gk.index_insert(con, rows, '2026-10-05') == 1
        assert gk.index_insert(con, rows, '2026-10-05') == 0   # nurl 唯一键挡住
        urls, titles = gk.index_keys(con)
        assert 'https://a/1' in urls and gk.norm_title('某省推进乡村振兴的调研报道') in titles

    def test_age_out_stale(self):
        con = _mem_db()
        gk.index_insert(con, [_row('https://a/old', '一条六十天前的旧闻标题', 's1', 60),
                              _row('https://a/new', '一条三天前的新鲜事标题', 's1', 3)],
                        '2026-10-05')
        aged = gk.index_age_out(con, 28, ['s1'], datetime.now())
        stale_titles = {con.execute('SELECT title FROM items WHERE id=?', (i,)).fetchone()[0]
                        for i in aged['stale']}
        assert '一条六十天前的旧闻标题' in stale_titles
        assert '一条三天前的新鲜事标题' not in stale_titles
        assert aged['archived'] == []

    def test_age_out_archived_disabled_source(self):
        con = _mem_db()
        gk.index_insert(con, [_row('https://a/x', '停用来源里的一条新内容', 'gone', 1)],
                        '2026-10-05')
        aged = gk.index_age_out(con, 28, ['s1'], datetime.now())
        assert len(aged['archived']) == 1

    def test_mark_and_candidates(self):
        con = _mem_db()
        gk.index_insert(con, [_row('https://a/1', '候选条目标题一号甲', 's1', 1)], '2026-10-05')
        ids = [r['id'] for r in gk.index_candidates(con, 'new')]
        assert len(ids) == 1
        gk.index_mark(con, ids, 'shown', when='2026-10-05')
        assert gk.index_candidates(con, 'new') == []


# ------------------------------------------------- 确定性剔除 / 降序（CLI 侧）

class TestJunk:
    def test_layout_signature(self):
        assert wk.junk_reason('一版责编：胡安琪 郭雪岩') == '版面署名'

    def test_no_body_form(self):
        assert wk.junk_reason('图片报道') == '无正文形态'
        assert wk.junk_reason('组图') == '无正文形态'

    def test_normal_title_not_junk(self):
        assert wk.junk_reason('某县推进乡村振兴的实践经验') == ''

    def test_graphic_rank(self):
        assert wk.graphic_rank('一图读懂《十四五规划》') == 1
        assert wk.graphic_rank('《十四五规划》正式印发') == 0
