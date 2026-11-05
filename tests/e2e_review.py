"""Browser test of the review flow (headless Firefox + Selenium). Not collected by pytest; run by hand
against a server on a THROWAWAY copy of the data:

    python tests/e2e_review.py http://localhost:8791 /tmp/shots
"""
import sys, time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
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
    wait.until(lambda _: 'All changes saved' in d.find_element(By.CSS_SELECTOR, '[role=status]').text)


def lens():
    return [e.text for e in css('.animal .len')]


try:
    d.get(base + '/#/')
    wait.until(lambda _: len(css('table.photos tbody tr')) > 10)
    time.sleep(2)
    d.save_screenshot(str(shots / '1_photos.png'))
    check('photo table lists photos', len(css('table.photos tbody tr')) > 100)

    css('.chip')[1].click()                                    # Needs review
    wait.until(lambda _: len(css('table.photos tbody tr')) < 20)
    check('status filter narrows the list', 0 < len(css('table.photos tbody tr')) < 20)

    d.find_element(By.XPATH, "//button[contains(., 'Review next')]").click()
    wait.until(lambda _: css('.animal') and d.execute_script(
        "const i=document.querySelector('.stage img'); return i && i.complete && i.naturalWidth > 0"))
    time.sleep(1)
    d.save_screenshot(str(shots / '2_review.png'))
    url1 = d.current_url
    check('review page shows animals with cm lengths', any(t.endswith(' cm') for t in lens()))

    body = d.find_element(By.TAG_NAME, 'body')
    n_acc0 = len(css('.animal .pill.accepted'))
    body.send_keys('a')
    saved()
    check('A accepts the selected animal (and autosaves)', len(css('.animal .pill.accepted')) == n_acc0 + 1)
    body.send_keys(Keys.CONTROL, 'z')
    saved()
    check('Ctrl+Z undoes it', len(css('.animal .pill.accepted')) == n_acc0)

    before = d.find_element(By.CSS_SELECTOR, '.animal.sel .len').text
    pt = css('circle[data-kind=point]')[-1]                    # a point of the selected animal (drawn last)
    ActionChains(d).click_and_hold(pt).move_by_offset(40, 25).move_by_offset(20, 10).release().perform()
    saved()
    after = d.find_element(By.CSS_SELECTOR, '.animal.sel .len').text
    check(f'dragging a keypoint changes the length ({before} -> {after})', before != after)
    check('edited animal offers "Restore model points"', bool(d.find_elements(By.XPATH, "//button[contains(., 'Restore model points')]")))

    body.send_keys('r')
    end = css('circle[data-kind=ruler]')[0]
    ActionChains(d).click_and_hold(end).move_by_offset(15, 5).move_by_offset(5, 0).release().perform()
    saved()
    check('dragging the auto ruler makes it manual with no pop-up',
          'Manual' in d.find_element(By.CSS_SELECTOR, '.panel h2').text and not css('dialog'))
    check('ruler distance field shows 15.0 cm', d.find_element(By.CSS_SELECTOR, '.panel .inline-num').get_attribute('value') == '15.0')
    d.save_screenshot(str(shots / '3_after_edits.png'))

    d.refresh()
    wait.until(lambda _: css('.animal'))
    time.sleep(1)
    check('ruler edit survives a reload', 'Manual' in d.find_element(By.CSS_SELECTOR, '.panel h2').text)
    edited = d.execute_async_script(
        "const done = arguments[0], id = location.hash.split('/').pop();"
        "fetch('/api/photos/' + id).then(r => r.json()).then(j => done(j.record.animals.filter(a => a.flags.edited).length));")
    check('keypoint edit was saved to the server', edited == 1)

    d.find_element(By.XPATH, "//button[contains(., 'Mark reviewed')]").click()
    wait.until(lambda _: d.current_url != url1)
    check('"Mark reviewed & next" moves to another photo', d.current_url != url1)
finally:
    d.quit()

print(f"{sum(ok for _, ok in results)}/{len(results)} checks passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
