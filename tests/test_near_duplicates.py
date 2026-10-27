from dr.core.pgindex import near_duplicate_groups


def test_versions_and_copies_group_other_texts_do_not():
    b4_2018 = "can ho b4 dien tich xay dung 55.78 m2 dien tich thong thuy 52.55 m2 phong bep phong an 11.84 m2 phong khach 13.49 m2"
    b4_2021 = "can ho b4 dien tich xay dung 56.72 m2 dien tich thong thuy 52.88 m2 phong bep phong an 11.84 m2 phong khach 13.49 m2"
    a6 = "can ho a6 dien tich xay dung 67.09 m2 dien tich thong thuy 63.41 m2 tien sanh 3.39 m2 phong bep 10.78 m2"
    groups = near_duplicate_groups([(1, b4_2018), (2, a6), (3, b4_2018), (4, b4_2021)], threshold=0.5)
    assert groups == [[1, 3, 4], [2]]


def test_threshold_keeps_loosely_related_texts_apart():
    a = "hop dong so 224/2022 cung cap va lap dat busway du an minh chau"
    b = "hop dong so 307/2022 cung cap va lap dat he thong pccc du an minh chau"
    assert near_duplicate_groups([(1, a), (2, b)]) == [[1], [2]]
