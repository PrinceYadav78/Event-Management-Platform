from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from models.models import CertificateTemplate, EventParticipant, Event, Student, CustomTemplate
from routers.auth import verify_token
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib import colors
import io
import os
import shutil
import uuid

router = APIRouter()
from templating import templates

UPLOAD_DIR = "static/templates_upload"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.get("/certificates", response_class=HTMLResponse)
async def certificates_page(request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    cert_templates = db.query(CertificateTemplate).all()
    custom_templates = db.query(CustomTemplate).all()
    events = db.query(Event).filter(Event.is_completed == True).all()
    return templates.TemplateResponse(request, "admin/certificates.html", {
        "cert_templates": cert_templates,
        "custom_templates": custom_templates,
        "events": events
    })

@router.get("/certificates/template/edit/{template_id}", response_class=HTMLResponse)
async def edit_template_page(template_id: str, request: Request, db: Session = Depends(get_db)):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    tmpl = db.query(CustomTemplate).filter(CustomTemplate.id == template_id).first()
    if not tmpl:
        return RedirectResponse(url="/certificates", status_code=303)
    return templates.TemplateResponse(request, "admin/certificate_editor.html", {
        "tmpl": tmpl,
        "active": "certificates"
    })

@router.post("/certificates/template/edit/{template_id}")
async def save_template_settings(
    template_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    tmpl = db.query(CustomTemplate).filter(CustomTemplate.id == template_id).first()
    if tmpl:
        tmpl.name_x = int(form.get("name_x", 50))
        tmpl.name_y = int(form.get("name_y", 45))
        tmpl.name_font_size = int(form.get("name_font_size", 36))
        tmpl.name_color = form.get("name_color", "#1a2535")
        tmpl.event_x = int(form.get("event_x", 50))
        tmpl.event_y = int(form.get("event_y", 58))
        tmpl.event_font_size = int(form.get("event_font_size", 20))
        tmpl.event_color = form.get("event_color", "#374151")
        tmpl.position_x = int(form.get("position_x", 50))
        tmpl.position_y = int(form.get("position_y", 65))
        tmpl.position_font_size = int(form.get("position_font_size", 24))
        tmpl.position_color = form.get("position_color", "#b45309")
        tmpl.house_x = int(form.get("house_x", 50))
        tmpl.house_y = int(form.get("house_y", 72))
        tmpl.house_font_size = int(form.get("house_font_size", 16))
        tmpl.house_color = form.get("house_color", "#374151")
        tmpl.date_x = int(form.get("date_x", 50))
        tmpl.date_y = int(form.get("date_y", 78))
        tmpl.date_font_size = int(form.get("date_font_size", 14))
        tmpl.date_color = form.get("date_color", "#6b7280")
        db.commit()
    return RedirectResponse(url="/certificates?msg=settings_saved", status_code=303)

@router.post("/certificates/template/save")
async def save_builtin_template(
    request: Request,
    name: str = Form(...),
    title_text: str = Form(...),
    body_text: str = Form(...),
    font_family: str = Form(...),
    is_default: bool = Form(False),
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    if is_default:
        for t in db.query(CertificateTemplate).all():
            t.is_default = False
    template = CertificateTemplate(
        name=name,
        title_text=title_text,
        body_text=body_text,
        font_family=font_family,
        is_default=is_default
    )
    db.add(template)
    db.commit()
    return RedirectResponse(url="/certificates?msg=saved", status_code=303)

@router.post("/certificates/template/upload")
async def upload_custom_template(
    request: Request,
    name: str = Form(...),
    template_file: UploadFile = File(...),
    is_default: bool = Form(False),
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    ext = os.path.splitext(template_file.filename)[1].lower()
    if ext not in [".docx", ".jpeg", ".jpg", ".png"]:
        return RedirectResponse(url="/certificates?msg=invalid_file", status_code=303)
    file_type = "docx" if ext == ".docx" else "image"
    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(template_file.file, f)
    if is_default:
        for t in db.query(CustomTemplate).all():
            t.is_default = False
    custom = CustomTemplate(
        name=name,
        filename=filename,
        file_type=file_type,
        is_default=is_default
    )
    db.add(custom)
    db.commit()
    return RedirectResponse(url=f"/certificates/template/edit/{custom.id}", status_code=303)

@router.post("/certificates/template/delete/{template_id}")
async def delete_custom_template(
    template_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    tmpl = db.query(CustomTemplate).filter(CustomTemplate.id == template_id).first()
    if tmpl:
        filepath = os.path.join(UPLOAD_DIR, tmpl.filename)
        if os.path.exists(filepath):
            os.remove(filepath)
        db.delete(tmpl)
        db.commit()
    return RedirectResponse(url="/certificates?msg=deleted", status_code=303)

@router.post("/certificates/template/set_default/{template_id}")
async def set_default_custom_template(
    template_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    for t in db.query(CustomTemplate).all():
        t.is_default = False
    tmpl = db.query(CustomTemplate).filter(CustomTemplate.id == template_id).first()
    if tmpl:
        tmpl.is_default = True
    db.commit()
    return RedirectResponse(url="/certificates?msg=default_set", status_code=303)

@router.get("/certificates/generate/{event_id}")
async def generate_certificates(
    event_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    if not verify_token(request):
        return RedirectResponse(url="/login", status_code=303)
    event = db.query(Event).filter(Event.id == event_id).first()
    winners = db.query(EventParticipant).filter(
        EventParticipant.event_id == event_id,
        EventParticipant.position != None
    ).order_by(EventParticipant.position).all()
    if not winners:
        return RedirectResponse(url="/certificates?msg=no_winners", status_code=303)
    custom_template = db.query(CustomTemplate).filter(
        CustomTemplate.is_default == True
    ).first()
    if custom_template:
        filepath = os.path.join(UPLOAD_DIR, custom_template.filename)
        if os.path.exists(filepath):
            if custom_template.file_type == "docx":
                return await generate_from_docx(filepath, winners, event)
            elif custom_template.file_type == "image":
                return await generate_from_image(filepath, winners, event, custom_template)
    return await generate_default_pdf(winners, event, db)

async def generate_from_docx(filepath, winners, event):
    from docx import Document
    import copy
    position_labels = {1: "1st", 2: "2nd", 3: "3rd"}
    buffer = io.BytesIO()
    merged_doc = Document()
    for i, winner in enumerate(winners):
        student = winner.student
        pos_label = position_labels.get(winner.position, f"{winner.position}th")
        replacements = {
            "{{name}}": student.name,
            "{{event}}": event.name,
            "{{position}}": pos_label,
            "{{house}}": student.house.name,
            "{{class}}": student.class_name,
            "{{date}}": str(event.event_date),
            "{{school}}": "National Public School",
        }
        temp_doc = Document(filepath)
        for para in temp_doc.paragraphs:
            for run in para.runs:
                for key, val in replacements.items():
                    if key in run.text:
                        run.text = run.text.replace(key, val)
        for table in temp_doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        for run in para.runs:
                            for key, val in replacements.items():
                                if key in run.text:
                                    run.text = run.text.replace(key, val)
        if i == 0:
            for element in temp_doc.element.body:
                merged_doc.element.body.append(copy.deepcopy(element))
        else:
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
            page_break = OxmlElement('w:p')
            pb_run = OxmlElement('w:r')
            pb = OxmlElement('w:br')
            pb.set(qn('w:type'), 'page')
            pb_run.append(pb)
            page_break.append(pb_run)
            merged_doc.element.body.append(page_break)
            for element in temp_doc.element.body:
                merged_doc.element.body.append(copy.deepcopy(element))
    merged_doc.save(buffer)
    buffer.seek(0)
    filename = f"certificates_{event.name.replace(' ', '_')}.docx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

async def generate_from_image(filepath, winners, event, tmpl):
    from PIL import Image as PILImage
    position_labels = {1: "1st", 2: "2nd", 3: "3rd"}
    buffer = io.BytesIO()

    # Detect image size and use as page size
    with PILImage.open(filepath) as img:
        img_width, img_height = img.size

    # Convert pixels to points (72 points per inch, assume 96 DPI)
    pt_width = img_width * 72 / 96
    pt_height = img_height * 72 / 96

    c = pdf_canvas.Canvas(buffer, pagesize=(pt_width, pt_height))

    for winner in winners:
        student = winner.student
        pos_label = position_labels.get(winner.position, f"{winner.position}th")

        # Draw background image filling entire page
        c.drawImage(filepath, 0, 0, width=pt_width, height=pt_height)

        def hex_to_rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i+2], 16)/255 for i in (0, 2, 4))

        def draw_text(text, x_pct, y_pct, font_size, color_hex):
            r, g, b = hex_to_rgb(color_hex)
            c.setFillColorRGB(r, g, b)
            c.setFont("Helvetica-Bold", font_size)
            # x_pct and y_pct are percentages of page dimensions
            x = pt_width * x_pct / 100
            # PDF y starts from bottom, so invert
            y = pt_height * (100 - y_pct) / 100
            c.drawCentredString(x, y, text)

        # Draw each field using saved positions
        draw_text(student.name, tmpl.name_x, tmpl.name_y,
                  tmpl.name_font_size, tmpl.name_color)
        draw_text(f"{pos_label} Place — {event.name}", tmpl.event_x, tmpl.event_y,
                  tmpl.event_font_size, tmpl.event_color)
        draw_text(pos_label, tmpl.position_x, tmpl.position_y,
                  tmpl.position_font_size, tmpl.position_color)
        draw_text(f"House: {student.house.name} | Class: {student.class_name}",
                  tmpl.house_x, tmpl.house_y,
                  tmpl.house_font_size, tmpl.house_color)
        draw_text(str(event.event_date), tmpl.date_x, tmpl.date_y,
                  tmpl.date_font_size, tmpl.date_color)

        c.showPage()

    c.save()
    buffer.seek(0)
    filename = f"certificates_{event.name.replace(' ', '_')}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

async def generate_default_pdf(winners, event, db):
    template = db.query(CertificateTemplate).filter(
        CertificateTemplate.is_default == True
    ).first()
    if not template:
        template = CertificateTemplate(
            title_text="Certificate of Achievement",
            body_text="This is to certify that {name} has achieved {position} place in {event} at National Public School.",
            font_family="Helvetica"
        )
    position_labels = {1: "1st", 2: "2nd", 3: "3rd"}
    buffer = io.BytesIO()
    page_width, page_height = landscape(A4)
    c = pdf_canvas.Canvas(buffer, pagesize=landscape(A4))
    for winner in winners:
        student = winner.student
        pos_label = position_labels.get(winner.position, f"{winner.position}th")
        body = template.body_text.replace("{name}", student.name)
        body = body.replace("{event}", event.name)
        body = body.replace("{position}", pos_label)
        c.setFillColorRGB(0.98, 0.97, 0.93)
        c.rect(0, 0, page_width, page_height, fill=1, stroke=0)
        c.setStrokeColorRGB(0.72, 0.58, 0.22)
        c.setLineWidth(3)
        c.rect(30, 30, page_width-60, page_height-60, fill=0, stroke=1)
        c.setLineWidth(1)
        c.rect(40, 40, page_width-80, page_height-80, fill=0, stroke=1)
        c.setFillColorRGB(0.15, 0.15, 0.35)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(page_width/2, page_height-80, "NATIONAL PUBLIC SCHOOL")
        c.setStrokeColorRGB(0.72, 0.58, 0.22)
        c.setLineWidth(1.5)
        c.line(page_width/2-180, page_height-95, page_width/2+180, page_height-95)
        c.setFillColorRGB(0.55, 0.40, 0.05)
        c.setFont("Helvetica-Bold", 36)
        c.drawCentredString(page_width/2, page_height-150, template.title_text.upper())
        c.setFillColorRGB(0.3, 0.3, 0.3)
        c.setFont("Helvetica", 13)
        c.drawCentredString(page_width/2, page_height-180, "This certificate is proudly presented to")
        c.setFillColorRGB(0.1, 0.15, 0.35)
        c.setFont("Helvetica-Bold", 30)
        c.drawCentredString(page_width/2, page_height-230, student.name)
        name_width = c.stringWidth(student.name, "Helvetica-Bold", 30)
        c.setStrokeColorRGB(0.72, 0.58, 0.22)
        c.setLineWidth(1)
        c.line(page_width/2-name_width/2, page_height-238, page_width/2+name_width/2, page_height-238)
        c.setFillColorRGB(0.25, 0.25, 0.25)
        c.setFont("Helvetica", 14)
        words = body.split()
        lines = []
        current_line = ""
        for word in words:
            test = current_line + " " + word if current_line else word
            if c.stringWidth(test, "Helvetica", 14) < page_width - 200:
                current_line = test
            else:
                lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        y = page_height - 275
        for line in lines:
            c.drawCentredString(page_width/2, y, line)
            y -= 22
        c.setFillColorRGB(0.45, 0.45, 0.45)
        c.setFont("Helvetica", 11)
        c.drawCentredString(page_width/2, page_height-340,
            f"House: {student.house.name}   |   Class: {student.class_name}   |   Date: {event.event_date}")
        c.setFillColorRGB(0.72, 0.58, 0.22)
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(page_width/2, page_height-370, f"{pos_label} Place — {event.name}")
        c.setStrokeColorRGB(0.72, 0.58, 0.22)
        c.setLineWidth(1.5)
        c.line(page_width/2-180, page_height-390, page_width/2+180, page_height-390)
        c.setStrokeColorRGB(0.5, 0.5, 0.5)
        c.setLineWidth(0.8)
        c.line(120, 80, 280, 80)
        c.line(page_width-280, 80, page_width-120, 80)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.setFont("Helvetica", 10)
        c.drawCentredString(200, 68, "Principal")
        c.drawCentredString(page_width-200, 68, "Class Teacher")
        c.showPage()
    c.save()
    buffer.seek(0)
    filename = f"certificates_{event.name.replace(' ', '_')}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )