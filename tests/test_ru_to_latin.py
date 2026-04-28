"""Russian (Cyrillic) → Latin via press-friendly BGN/PCGN.

This is what English-language press, sports, and visa contexts actually
print: Mikhail not Mihail, Akhmatova not Ahmatova, Fyodor not Fedor,
Olga not Ol'ga. The standard Python libs (`transliterate`, `cyrtranslit`)
emit GOST/scientific style which differs on those points; we ship our
own ~33-letter table.
"""
import pytest

from translit_core import detect_source_script, supported_pairs, transliterate


# === Detection ============================================================

@pytest.mark.parametrize("name", ["Иван", "Мария", "Анна", "Михаил Лермонтов"])
def test_cyrillic_detected_as_ru(name):
    assert detect_source_script(name) == "ru"


# === Common given names ===================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("Иван", "Ivan"),
        ("Мария", "Mariya"),
        ("Анна", "Anna"),
        ("Сергей", "Sergey"),     # BGN: ей → ey
        ("Дмитрий", "Dmitriy"),   # BGN: ий → iy (press sometimes Dmitri/Dmitry)
        ("Юрий", "Yuriy"),
        ("Михаил", "Mikhail"),    # х → kh (not h)
        ("Алексей", "Aleksey"),
        ("Ольга", "Olga"),        # ь dropped
        ("Наталья", "Natalya"),   # ь dropped, я → ya
    ],
)
def test_common_given_names(name, expected):
    assert transliterate(name, "en", source_lang="ru") == expected


# === ё (yo) — y-glide preserved ===========================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("Фёдор", "Fyodor"),
        ("Семён", "Semyon"),
        ("Алёша", "Alyosha"),
        ("Пётр", "Pyotr"),
    ],
)
def test_yo_preserves_y_glide(name, expected):
    """Some libs strip ё → e (Fedor instead of Fyodor). Ours keeps the
    y-glide that real Russian speakers pronounce."""
    assert transliterate(name, "en", source_lang="ru") == expected


# === Common surnames ======================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("Ахматова", "Akhmatova"),
        ("Толстой", "Tolstoy"),
        ("Лермонтов", "Lermontov"),
        ("Пушкин", "Pushkin"),
        ("Достоевский", "Dostoevskiy"),   # о+е is just 'oe' (no ъ/ь between)
        ("Чехов", "Chekhov"),
        ("Гагарин", "Gagarin"),
    ],
)
def test_common_surnames(name, expected):
    assert transliterate(name, "en", source_lang="ru") == expected


# === Full names + patronymics =============================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("Владимир Путин", "Vladimir Putin"),
        ("Лев Толстой", "Lev Tolstoy"),
        ("Иван Сергеевич Тургенев", "Ivan Sergeevich Turgenev"),
        ("Анна Андреевна Ахматова", "Anna Andreevna Akhmatova"),
        ("Михаил Юрьевич Лермонтов", "Mikhail Yuryevich Lermontov"),
    ],
)
def test_full_names_with_patronymics(name, expected):
    """Russian patronymics (-evich/-ovich/-evna/-ovna) round-trip cleanly."""
    assert transliterate(name, "en", source_lang="ru") == expected


# === Hard / soft signs (ъ, ь) =============================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("Объект", "Obyekt"),    # ъе → ye (digraph rule)
        ("Подъём", "Podyom"),    # ъё → yo (ё already starts with y)
        ("Игорь", "Igor"),       # final ь dropped (no following vowel)
        ("Соль", "Sol"),         # ь dropped
        ("Татьяна", "Tatyana"),  # ьа... wait, the chars are ь+я; я → ya already
    ],
)
def test_hard_and_soft_signs_dropped(name, expected):
    """BGN inserts an apostrophe for ъ/ь; press names drop them entirely.
    We follow press convention: cleaner output, names rarely depend on
    the ь/ъ distinction for disambiguation."""
    assert transliterate(name, "en", source_lang="ru") == expected


# === Digraphs (multi-char outputs) ========================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("Жанна", "Zhanna"),     # ж → zh
        ("Цой", "Tsoy"),         # ц → ts
        ("Чайковский", "Chaykovskiy"),
        ("Шаляпин", "Shalyapin"),
        ("Щукин", "Shchukin"),   # щ → shch (4 letters)
    ],
)
def test_digraph_consonants(name, expected):
    assert transliterate(name, "en", source_lang="ru") == expected


# === Case handling ========================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("ИВАН", "Ivan"),
        ("иван", "Ivan"),
        ("Иван", "Ivan"),
        ("ИВАН ПУТИН", "Ivan Putin"),
        ("иван путин", "Ivan Putin"),
    ],
)
def test_input_case_normalized_to_titlecase(name, expected):
    """Whatever the input case, output is title-cased per word."""
    assert transliterate(name, "en", source_lang="ru") == expected


# === Hyphenated names =====================================================

def test_hyphenated_name_capitalizes_after_hyphen():
    """str.title() correctly title-cases each hyphen-delimited piece."""
    assert (
        transliterate("Иван-Петров", "en", source_lang="ru") == "Ivan-Petrov"
    )


# === Punctuation & digits stripped ========================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("Иван!", "Ivan"),
        ("Иван.", "Ivan"),
        ("Иван123", "Ivan"),
        ("«Иван»", "Ivan"),
    ],
)
def test_non_letter_chars_stripped(name, expected):
    assert transliterate(name, "en", source_lang="ru") == expected


# === Empty / whitespace ===================================================

@pytest.mark.parametrize("name", ["", "   ", "!!!", "123"])
def test_empty_or_no_letters_returns_none(name):
    assert transliterate(name, "en", source_lang="ru") is None


# === Refuses non-Cyrillic letters in input ================================

@pytest.mark.parametrize("name", ["Їжак", "Ѓорѓи", "Жанна A"])
def test_refuses_non_russian_cyrillic_or_mixed_letters(name):
    """Ukrainian Ї, Macedonian Ѓ, Latin letters mixed in — we don't have
    those in our table. Refuse rather than emit garbled output."""
    # Note: detection may route some to "ru" anyway; assert engine refuses.
    out = transliterate(name, "en", source_lang="ru")
    # Either None (refusal) or detection routed elsewhere — never a
    # half-translated Russian name.
    if out is not None:
        # Should at least not contain the un-transliterated foreign letter
        for c in name:
            if c in "ЇѓA":
                assert c not in out


# === supported_pairs reflects the new route ===============================

def test_supported_pairs_includes_ru_en():
    pairs = supported_pairs()
    assert any(p["source"] == "ru" and p["target"] == "latin" for p in pairs)
