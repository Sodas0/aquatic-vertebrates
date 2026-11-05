"""Browser test of upload + background prediction with the REAL models (needs the GPU and the ml extras).
Run against a server on a THROWAWAY copy of the data:

    python tests/e2e_predict.py http://localhost:8792 /tmp/shots /path/to/new_photo.jpg /path/to/duplicate_photo.jpg
"""
import sys, time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

base, shots, new_photo, dup_photo = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4]
shots.mkdir(parents=True, exist_ok=True)
opts = webdriver.FirefoxOptions()
opts.add_argument('-headless')
d = webdriver.Firefox(options=opts)
d.set_window_size(1440, 900)
wait = WebDriverWait(d, 240)
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def css(sel):
    return d.find_elements(By.CSS_SELECTOR, sel)


try:
    d.get(base + '/#/')
    wait.until(lambda _: len(css('table.photos tbody tr')) > 10)
    n0 = d.execute_script("return fetch('/api/photos').then(r => r.json()).then(j => j.counts.all)")

    # duplicate upload is recognised
    css('[data-testid=file-input]')[0].send_keys(dup_photo)
    wait.until(lambda _: css('.notice') and 'already here' in css('.notice')[0].text)
    check('re-uploading an existing photo is recognised as a duplicate', 'already here' in css('.notice')[0].text)

    # new photo with "predict after adding" on
    css('[data-testid=file-input]')[0].send_keys(new_photo)
    wait.until(lambda _: css('.notice') and 'Added 1 photo' in css('.notice')[0].text)
    check('new photo is added and queued for prediction', 'predicting in the background' in css('.notice')[0].text)
    check('a progress indicator appears in the top bar', bool(css('.jobpill')))
    d.save_screenshot(str(shots / '1_uploaded.png'))
    t0 = time.time()
    wait.until(lambda _: not css('.jobpill'))
    secs = time.time() - t0
    n1 = d.execute_script("return fetch('/api/photos').then(r => r.json()).then(j => j.counts.all)")
    check('photo count went up by one', n1 == n0 + 1)
    row = d.find_element(By.XPATH, f"//table//tr[.//button[normalize-space()='{Path(new_photo).name}']]")
    check(f'the new photo finished predicting ({secs:.0f}s) and needs review', 'Needs review' in row.text)

    row.find_element(By.XPATH, ".//button[normalize-space()='Review']").click()
    wait.until(lambda _: css('.animal') and d.execute_script(
        "const i=document.querySelector('.stage img'); return i && i.complete && i.naturalWidth > 0"))
    time.sleep(1)
    d.save_screenshot(str(shots / '2_predicted.png'))
    check('predicted animals listed with cm lengths', any(e.text.endswith(' cm') for e in css('.animal .len')))
    check('ruler auto-detected', 'Auto-detected' in d.find_element(By.CSS_SELECTOR, '.panel h2').text)
    check('confidence shown per animal', bool(css('.animal .conf')))

    # predict from the review page on an unprocessed, unlabeled photo
    empty_id = d.execute_async_script(
        "const done = arguments[0]; fetch('/api/photos?status=new').then(r => r.json())"
        ".then(j => done(j.items.find(i => i.n_animals === 0).id));")
    d.get(base + '/#/review/' + empty_id)
    wait.until(lambda _: css('.empty-card'))
    d.find_element(By.XPATH, "//div[contains(@class,'empty-card')]//button[normalize-space()='Predict']").click()
    wait.until(lambda _: css('.animal'))
    check('"Predict" on an empty photo fills it in without a reload', len(css('.animal')) > 0)
    d.save_screenshot(str(shots / '3_predict_from_review.png'))
finally:
    d.quit()

print(f"{sum(ok for _, ok in results)}/{len(results)} checks passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
