"""Regression checks for the independent covers/title print profile."""
from pathlib import Path
import tempfile,json,copy
from pypdf import PdfWriter
from validate_book_package import validate

def run():
 with tempfile.TemporaryDirectory() as tmp:
  r=Path(tmp)
  def pdf(name,n):
   w=PdfWriter()
   for _ in range(n):w.add_blank_page(210*72/25.4,148*72/25.4)
   w.write(r/name)
  pdf('book.pdf',8)
  for name,n in [('front.pdf',1),('title.pdf',1),('body.pdf',2),('back.pdf',1)]:pdf(name,n)
  for f in ['print.md','preview.jpg','covers.jpg','language.md']:(r/f).write_text('fixture')
  roles=['cover','inside-cover','title','blank','story','ending','inside-back-cover','back-cover']
  b={'title':'Test','audience_age':'4','book_type':'science','language':'zh-CN','binding':'ring','page_count':8,'format':{'paper':'A5','width_mm':210,'height_mm':148},'pages':[{'page':i+1,'role':role,'layout':'blank' if i in [1,3,6] else role,'blank':i in [1,3,6]} for i,role in enumerate(roles)],'printing':{'profile':'separate-covers-title','title_single_sided':True,'sheets':4,'jobs':[{'file':f,'source_pages':ps,'mode':m,'sheets':n} for f,ps,m,n in [('front.pdf',[1],'simplex',1),('title.pdf',[3],'simplex',1),('body.pdf',[5,6],'duplex',1),('back.pdf',[8],'simplex',1)]]},'deliverables':{'reading_pdf':'book.pdf','home_print_pdf':'book.pdf','printing_instructions':'print.md','full_preview':'preview.jpg','cover_back_preview':'covers.jpg'},'language_review':'language.md','qa':{'story_reviewed':True,'language_reviewed':True,'visual_continuity_reviewed':True,'pdf_rendered_reviewed':True,'print_tested':False},'print_status':'pending-physical-proof'}
  def check(obj):
   (r/'book.json').write_text(json.dumps(obj));return validate(r)
  errors,warnings=check(b);assert not errors,errors;assert any('print_tested' in w for w in warnings)
  single=copy.deepcopy(b);single['printing']['delivery_mode']='single-pdf';single['printing']['jobs']=[]
  assert not check(single)[0],check(single)[0]
  bad=copy.deepcopy(b);bad['pages'][1]['blank']=False;assert any('inside-cover' in e for e in check(bad)[0])
  bad=copy.deepcopy(b);bad['pages'][3]['lines']=['unexpected text'];assert any('blank' in e for e in check(bad)[0])
  bad=copy.deepcopy(b);bad['printing']['sheets']=3;assert any('sheets' in e for e in check(bad)[0])
  bad=copy.deepcopy(b);bad['printing']['jobs'][1]['source_pages']=[2];assert any('source_pages' in e for e in check(bad)[0])
  bad=copy.deepcopy(b);bad['printing']['jobs'][0]['mode']='duplex';assert any('mode' in e for e in check(bad)[0])
  bad=copy.deepcopy(b);bad['print_status']='print-verified';assert any('print_tested' in e for e in check(bad)[0])
  print('Print profile: single/split packages + 6 failure cases passed.')
if __name__=='__main__':run()
