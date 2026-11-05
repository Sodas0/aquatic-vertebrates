"""Browser test of hand labeling (headless Firefox + Selenium). Run by hand against a server on a
THROWAWAY copy of the data:

    python tests/e2e_label.py http://localhost:8792 /tmp/shots
"""
import sys, time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

base, shots = sys.argv[1], Path(sys.argv[2])
shots.mkdir(parents=True, exist_ok=True)
opts = webdriver.FirefoxOptions()
opts.add_argument('-headless')
d = webdriver.Firefox(options=opts)
d.set_window_size(1440, 900)
wait = WebDriverWait(d, 30)
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def css(sel):
    return d.find_elements(By.CSS_SELECTOR, sel)


def saved():
    time.sleep(0.2)
    wait.until(lambda _: 'All changes saved' in d.find_element(By.CSS_SELECTOR, '[role=status]').text)


def record():
    return d.execute_async_script(
        "const done = arguments[0], id = location.hash.split('/').pop();"
        "fetch('/api/photos/' + id).then(r => r.json()).then(j => done(j.record));")


def click_stage(fx, fy, alt=False):
    """Click at a fraction of the stage's size."""
    st = d.find_element(By.CSS_SELECTOR, '[data-testid=stage]')
    w, h = st.size['width'], st.size['height']
    a = ActionChains(d).move_to_element_with_offset(st, int((fx - 0.5) * w), int((fy - 0.5) * h))
    if alt:
        a = a.key_down(Keys.ALT).click().key_up(Keys.ALT)
    else:
        a = a.click()
    a.perform()
    time.sleep(0.15)


try:
    d.get(base + '/#/')
    wait.until(lambda _: len(css('table.photos tbody tr')) > 10)
    d.find_element(By.CSS_SELECTOR, '.page input[placeholder="Search photos"]')
    name_box = d.find_element(By.CSS_SELECTOR, 'header input')
    name_box.send_keys('tester')
    css('.chip')[3].click()                                    # Not processed
    wait.until(lambda _: css('table.photos tbody tr'))
    label_btns = d.find_elements(By.XPATH, "//table//button[normalize-space()='Label']")
    check('unprocessed photos offer a "Label" action', bool(label_btns))
    empty_id = d.execute_async_script(                         # a photo nobody has started labeling
        "const done = arguments[0]; fetch('/api/photos?status=new').then(r => r.json())"
        ".then(j => done(j.items.find(i => i.n_animals === 0).id));")
    d.get(base + '/#/review/' + empty_id)
    wait.until(lambda _: css('.empty-card') and d.execute_script(
        "const i=document.querySelector('.stage img'); return i && i.complete && i.naturalWidth > 0"))
    first_url = d.current_url
    check('empty photo shows "Label by hand"', 'Label by hand' in d.find_element(By.CSS_SELECTOR, '.empty-card').text)
    d.save_screenshot(str(shots / '1_empty.png'))

    # ruler first: two clicks
    body = d.find_element(By.TAG_NAME, 'body')
    body.send_keys('r')
    click_stage(0.35, 0.80); click_stage(0.65, 0.80)
    saved()
    check('ruler drawn with two clicks (no pop-up)', record()['ruler'] and record()['ruler']['length_mm'] == 150)

    # add an animal: 3 clicks + Enter
    d.find_element(By.XPATH, "//button[contains(., 'Label by hand')]").click() if css('.empty-card') else body.send_keys('n')
    for fx in (0.30, 0.42, 0.55):
        click_stage(fx, 0.40 + (0.03 if fx == 0.42 else 0))
    body.send_keys(Keys.ENTER)
    saved()
    r = record()
    check('Add animal: 3 clicks + Enter creates a hand label',
          len(r['animals']) == 1 and len(r['animals'][0]['midline']) == 3 and r['animals'][0]['source'] == {'kind': 'human', 'name': 'tester'})
    check('new animal shows a cm length', d.find_element(By.CSS_SELECTOR, '.animal .len').text.endswith(' cm'))

    # second animal as salamander, then back to select
    body.send_keys('2')
    for fx in (0.30, 0.45, 0.60):
        click_stage(fx, 0.60)
    body.send_keys(Keys.ENTER)
    saved()
    body.send_keys(Keys.ESCAPE)
    r = record()
    check('species key applies to the next animal only', len(r['animals']) == 2 and r['animals'][1]['species'] == 'salamander'
          and r['animals'][0]['species'] == 'trout')

    # insert a point by double-clicking the line, remove it with Alt-click
    st = d.find_element(By.CSS_SELECTOR, '[data-testid=stage]')
    w, h = st.size['width'], st.size['height']
    ActionChains(d).move_to_element_with_offset(st, int((0.375 - 0.5) * w), int((0.60 - 0.5) * h)).double_click().perform()
    saved()
    n_after_insert = len(record()['animals'][1]['midline'])
    check('double-click on a line inserts a point', n_after_insert == 4)
    click_stage(0.375, 0.60, alt=True)
    saved()
    check('Alt-click removes a point', len(record()['animals'][1]['midline']) == 3)

    # vent on the salamander -> SVL shown
    body.send_keys('t')
    click_stage(0.40, 0.61)
    saved()
    check('vent placed; SVL appears in the list', record()['animals'][1]['vent'] is not None
          and 'SVL' in d.find_element(By.CSS_SELECTOR, '.animal.sel').text)

    # redraw animal 1
    css('.animal .head')[0].click()
    body.send_keys('d')
    for fx in (0.28, 0.36, 0.44, 0.52):
        click_stage(fx, 0.35)
    body.send_keys(Keys.ENTER)
    saved()
    check('Redraw replaces the midline', len(record()['animals'][0]['midline']) == 4)
    d.save_screenshot(str(shots / '2_labeled.png'))

    # delete + undo
    body.send_keys(Keys.DELETE)
    saved()
    check('Delete removes the animal', len(record()['animals']) == 1)
    body.send_keys(Keys.CONTROL, 'z')
    saved()
    check('Ctrl+Z restores it', len(record()['animals']) == 2)

    # finish
    d.find_element(By.XPATH, "//button[contains(., 'Done & next')]").click()
    wait.until(lambda _: d.current_url != first_url)
    check('"Done & next" goes to the next unlabeled photo', d.current_url != first_url)
    d.get(first_url)
    wait.until(lambda _: css('.rv-bar .pill'))
    check('the labeled photo is now Reviewed', 'Reviewed' in d.find_element(By.CSS_SELECTOR, '.rv-bar .pill').text)
finally:
    d.quit()

print(f"{sum(ok for _, ok in results)}/{len(results)} checks passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
