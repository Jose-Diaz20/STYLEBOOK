"""Pruebas del promedio de calificaciones por servicio en el catálogo público."""
from tests.test_flujos import escenario


def test_catalogo_muestra_promedio_y_total_de_opiniones_por_servicio(cliente_http, db):
    _, _, servicio_id = escenario(db)
    servicio = next(s for s in db.tablas["servicios"] if s["id"] == servicio_id)
    servicio["calificacion_promedio"] = 4.5
    servicio["total_calificaciones"] = 2

    html = cliente_http.get("/servicios").get_data(as_text=True)

    assert "Corte clásico VIP" in html
    assert "4.5" in html
    assert "2 opiniones" in html
    assert "Sin calificaciones" not in html


def test_catalogo_indica_cuando_un_servicio_aun_no_tiene_opiniones(cliente_http, db):
    escenario(db)

    html = cliente_http.get("/servicios").get_data(as_text=True)

    assert "Corte clásico VIP" in html
    assert "Sin calificaciones" in html
