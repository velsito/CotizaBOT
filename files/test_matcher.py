"""
Test Suite para Template Matching
Valida funcionalidad, precisión y rendimiento del sistema
"""

import unittest
import numpy as np
import cv2
import json
from pathlib import Path
import tempfile
import shutil
from template_matcher import TemplateMatcher, Detection


class TestDetectionClass(unittest.TestCase):
    """Tests para clase Detection"""
    
    def test_detection_creation(self):
        det = Detection(
            material='fusible',
            x=100, y=200,
            width=50, height=30,
            confidence=0.85,
            angle=90,
            scale=1.1
        )
        
        self.assertEqual(det.material, 'fusible')
        self.assertEqual(det.x, 100)
        self.assertEqual(det.confidence, 0.85)
    
    def test_bbox_calculation(self):
        det = Detection('test', 10, 20, 30, 40, 0.9, 0, 1.0)
        bbox = det.get_bbox()
        
        self.assertEqual(bbox, (10, 20, 40, 60))  # (x1, y1, x2, y2)
    
    def test_to_dict(self):
        det = Detection('test', 0, 0, 10, 10, 0.9, 0, 1.0)
        d = det.to_dict()
        
        self.assertIsInstance(d, dict)
        self.assertIn('material', d)
        self.assertIn('confidence', d)


class TestIOUCalculation(unittest.TestCase):
    """Tests para cálculo de IoU"""
    
    def setUp(self):
        self.matcher = TemplateMatcher(templates_dir=tempfile.mkdtemp())
    
    def test_perfect_overlap(self):
        """Dos boxes idénticos deben tener IoU = 1.0"""
        box1 = (0, 0, 10, 10)
        box2 = (0, 0, 10, 10)
        
        iou = self.matcher._calculate_iou(box1, box2)
        self.assertAlmostEqual(iou, 1.0)
    
    def test_no_overlap(self):
        """Boxes sin superposición deben tener IoU = 0.0"""
        box1 = (0, 0, 10, 10)
        box2 = (20, 20, 30, 30)
        
        iou = self.matcher._calculate_iou(box1, box2)
        self.assertEqual(iou, 0.0)
    
    def test_partial_overlap(self):
        """Test de superposición parcial"""
        box1 = (0, 0, 10, 10)  # Área = 100
        box2 = (5, 5, 15, 15)  # Área = 100
        # Intersección = 25 (5x5), Unión = 175
        # IoU = 25/175 ≈ 0.143
        
        iou = self.matcher._calculate_iou(box1, box2)
        self.assertAlmostEqual(iou, 0.143, places=2)
    
    def test_contained_box(self):
        """Box pequeño contenido en box grande"""
        box1 = (0, 0, 20, 20)  # Área = 400
        box2 = (5, 5, 15, 15)  # Área = 100
        # Intersección = 100, Unión = 400
        # IoU = 100/400 = 0.25
        
        iou = self.matcher._calculate_iou(box1, box2)
        self.assertAlmostEqual(iou, 0.25)


class TestNMS(unittest.TestCase):
    """Tests para Non-Maximum Suppression"""
    
    def setUp(self):
        self.matcher = TemplateMatcher(
            templates_dir=tempfile.mkdtemp(),
            nms_iou_threshold=0.5
        )
    
    def test_empty_list(self):
        result = self.matcher._non_maximum_suppression([])
        self.assertEqual(result, [])
    
    def test_single_detection(self):
        det = Detection('test', 0, 0, 10, 10, 0.9, 0, 1.0)
        result = self.matcher._non_maximum_suppression([det])
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], det)
    
    def test_duplicate_removal(self):
        """Dos detecciones casi idénticas, debe mantener la de mayor confianza"""
        det1 = Detection('test', 0, 0, 10, 10, 0.9, 0, 1.0)
        det2 = Detection('test', 1, 1, 10, 10, 0.8, 0, 1.0)  # 95% overlap
        
        result = self.matcher._non_maximum_suppression([det1, det2])
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].confidence, 0.9)
    
    def test_keep_distant_detections(self):
        """Detecciones distantes deben mantenerse ambas"""
        det1 = Detection('test', 0, 0, 10, 10, 0.9, 0, 1.0)
        det2 = Detection('test', 100, 100, 10, 10, 0.8, 0, 1.0)
        
        result = self.matcher._non_maximum_suppression([det1, det2])
        
        self.assertEqual(len(result), 2)


class TestTemplateRotation(unittest.TestCase):
    """Tests para rotación de plantillas"""
    
    def setUp(self):
        self.matcher = TemplateMatcher(templates_dir=tempfile.mkdtemp())
    
    def test_rotation_0(self):
        """Rotación de 0° debe retornar imagen idéntica"""
        template = np.ones((10, 20), dtype=np.uint8) * 128
        rotated = self.matcher._rotate_template(template, 0)
        
        np.testing.assert_array_equal(template, rotated)
    
    def test_rotation_90(self):
        """Rotación de 90° debe intercambiar dimensiones"""
        template = np.ones((10, 20), dtype=np.uint8)
        rotated = self.matcher._rotate_template(template, 90)
        
        # Dimensiones deben intercambiarse aproximadamente
        self.assertGreater(rotated.shape[0], rotated.shape[1])
    
    def test_rotation_preserves_pixels(self):
        """La rotación no debe perder información dramáticamente"""
        template = np.random.randint(0, 256, (20, 20), dtype=np.uint8)
        rotated = self.matcher._rotate_template(template, 45)
        
        # El área rotada debe ser similar
        ratio = rotated.size / template.size
        self.assertGreater(ratio, 0.5)
        self.assertLess(ratio, 3.0)


class TestTemplateScaling(unittest.TestCase):
    """Tests para escalado de plantillas"""
    
    def setUp(self):
        self.matcher = TemplateMatcher(templates_dir=tempfile.mkdtemp())
    
    def test_scale_1(self):
        """Escala 1.0 debe retornar imagen idéntica"""
        template = np.ones((10, 20), dtype=np.uint8)
        scaled = self.matcher._scale_template(template, 1.0)
        
        np.testing.assert_array_equal(template, scaled)
    
    def test_scale_up(self):
        """Escalar 2x debe duplicar dimensiones"""
        template = np.ones((10, 20), dtype=np.uint8)
        scaled = self.matcher._scale_template(template, 2.0)
        
        self.assertEqual(scaled.shape, (20, 40))
    
    def test_scale_down(self):
        """Escalar 0.5x debe reducir a la mitad"""
        template = np.ones((20, 40), dtype=np.uint8)
        scaled = self.matcher._scale_template(template, 0.5)
        
        self.assertEqual(scaled.shape, (10, 20))
    
    def test_invalid_scale(self):
        """Escala muy pequeña debe retornar None"""
        template = np.ones((20, 20), dtype=np.uint8)
        scaled = self.matcher._scale_template(template, 0.01)
        
        self.assertIsNone(scaled)


class TestIntegration(unittest.TestCase):
    """Tests de integración end-to-end"""
    
    def setUp(self):
        # Crear directorio temporal para templates
        self.temp_dir = tempfile.mkdtemp()
        self.templates_dir = Path(self.temp_dir) / "templates"
        self.templates_dir.mkdir()
        
        # Crear template de prueba (cuadrado blanco)
        template = np.ones((30, 30), dtype=np.uint8) * 255
        cv2.rectangle(template, (5, 5), (25, 25), 0, -1)
        cv2.imwrite(str(self.templates_dir / "test_component_v1.png"), template)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
    
    def test_template_loading(self):
        """Verificar carga correcta de plantillas"""
        matcher = TemplateMatcher(templates_dir=str(self.templates_dir))
        
        self.assertIn('test_component', matcher.templates)
        self.assertEqual(len(matcher.templates['test_component']), 1)
    
    def test_detection_on_synthetic_image(self):
        """Test en imagen sintética con componente conocido"""
        # Crear imagen con el componente
        image = np.ones((200, 200), dtype=np.uint8) * 255
        
        # Insertar componente en posición conocida
        template = np.ones((30, 30), dtype=np.uint8) * 255
        cv2.rectangle(template, (5, 5), (25, 25), 0, -1)
        
        x, y = 50, 80
        image[y:y+30, x:x+30] = template
        
        # Guardar template
        cv2.imwrite(str(self.templates_dir / "square_v1.png"), template)
        
        # Crear matcher y detectar
        matcher = TemplateMatcher(
            templates_dir=str(self.templates_dir),
            threshold=0.8
        )
        
        detections = matcher._match_template_variants(image, template, 'square')
        
        # Aplicar NMS
        filtered = matcher._non_maximum_suppression(detections)
        
        # Debe detectar al menos un componente
        self.assertGreater(len(filtered), 0)
        
        # La detección debe estar cerca de la posición real
        det = filtered[0]
        self.assertAlmostEqual(det.x, x, delta=5)
        self.assertAlmostEqual(det.y, y, delta=5)


class TestPerformance(unittest.TestCase):
    """Tests de rendimiento"""
    
    def test_nms_speed(self):
        """NMS debe ser eficiente incluso con muchas detecciones"""
        import time
        
        # Crear 1000 detecciones aleatorias
        detections = []
        for i in range(1000):
            det = Detection(
                material='test',
                x=np.random.randint(0, 1000),
                y=np.random.randint(0, 1000),
                width=20,
                height=20,
                confidence=np.random.random(),
                angle=0,
                scale=1.0
            )
            detections.append(det)
        
        matcher = TemplateMatcher(templates_dir=tempfile.mkdtemp())
        
        start = time.time()
        result = matcher._non_maximum_suppression(detections)
        elapsed = time.time() - start
        
        # NMS debe completarse en menos de 1 segundo
        self.assertLess(elapsed, 1.0)
        print(f"\nNMS procesó {len(detections)} detecciones en {elapsed:.3f}s")
        print(f"Resultado: {len(result)} detecciones finales")


def run_validation_suite():
    """Ejecuta suite completa de validación"""
    print("=" * 70)
    print("SUITE DE VALIDACIÓN - TEMPLATE MATCHING")
    print("=" * 70)
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Agregar todas las clases de test
    suite.addTests(loader.loadTestsFromTestCase(TestDetectionClass))
    suite.addTests(loader.loadTestsFromTestCase(TestIOUCalculation))
    suite.addTests(loader.loadTestsFromTestCase(TestNMS))
    suite.addTests(loader.loadTestsFromTestCase(TestTemplateRotation))
    suite.addTests(loader.loadTestsFromTestCase(TestTemplateScaling))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformance))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Resumen
    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)
    print(f"Tests ejecutados: {result.testsRun}")
    print(f"Exitosos: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Fallidos: {len(result.failures)}")
    print(f"Errores: {len(result.errors)}")
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_validation_suite()
    exit(0 if success else 1)
