import os
import pymupdf
from typing import Dict, Any, List

def analyze_page_image(image_path: str) -> Dict[str, Any]:
    """
    Lightweight, CPU-friendly visual region analyzer optimized for Raspberry Pi 3B.
    Performs block consolidation to merge fragmented ink blobs into line/paragraph text candidates.
    Uses pure Python on grid-sampling without OpenCV/NumPy.
    """
    if not os.path.exists(image_path):
        return {"analysis_successful": False, "error": f"Image not found: {image_path}"}
        
    try:
        pix = pymupdf.Pixmap(image_path)
        w, h = pix.width, pix.height
        n_components = pix.n
        samples = pix.samples
        
        # Grid size of 8x8 pixels
        grid_size = 8
        ink_cells = set()
        
        # 4-point check inside each 8x8 cell to prevent thin stroke/handwriting misses
        offsets = [(0, 0), (4, 0), (0, 4), (4, 4)]
        
        for cy in range(0, h, grid_size):
            for cx in range(0, w, grid_size):
                is_ink = False
                for dx, dy in offsets:
                    px = cx + dx
                    py = cy + dy
                    if px < w and py < h:
                        idx = (py * w + px) * n_components
                        if n_components == 1 or n_components == 2:
                            intensity = samples[idx]
                        elif n_components >= 3:
                            intensity = (samples[idx] + samples[idx+1] + samples[idx+2]) // 3
                        else:
                            intensity = 255
                            
                        if intensity < 200:
                            is_ink = True
                            break
                            
                if is_ink:
                    ink_cells.add((cx // grid_size, cy // grid_size))
        
        visited = set()
        raw_blobs = []
        
        for cell in ink_cells:
            if cell in visited:
                continue
                
            q = [cell]
            visited.add(cell)
            min_x, min_y = cell[0], cell[1]
            max_x, max_y = cell[0], cell[1]
            cell_count = 0
            
            while q:
                cx, cy = q.pop()
                cell_count += 1
                
                if cx < min_x: min_x = cx
                if cx > max_x: max_x = cx
                if cy < min_y: min_y = cy
                if cy > max_y: max_y = cy
                
                for nx, ny in ((cx-1, cy), (cx+1, cy), (cx, cy-1), (cx, cy+1), 
                               (cx-1, cy-1), (cx+1, cy+1), (cx+1, cy-1), (cx-1, cy+1)):
                    neighbor = (nx, ny)
                    if neighbor in ink_cells and neighbor not in visited:
                        visited.add(neighbor)
                        q.append(neighbor)
                        
            raw_blobs.append({
                'gx': min_x, 'gy': min_y, 
                'gw': max_x - min_x + 1, 'gh': max_y - min_y + 1,
                'cells': cell_count
            })
            
        # Stage 2B.1 Hardening: Generous merge thresholds to combine character fragments into lines/paragraphs
        merge_dx = 12  # ~96px horizontal gap tolerance for words on the same line
        merge_dy = 6   # ~48px vertical gap tolerance for stacked lines/paragraphs
        
        parent = {i: i for i in range(len(raw_blobs))}
        
        def find(i: int) -> int:
            if parent[i] == i: return i
            parent[i] = find(parent[i])
            return parent[i]
            
        def union(i: int, j: int):
            root_i = find(i)
            root_j = find(j)
            if root_i != root_j:
                parent[root_i] = root_j

        raw_blobs.sort(key=lambda b: (b['gy'], b['gx']))
        
        for i in range(len(raw_blobs)):
            b1 = raw_blobs[i]
            for j in range(i + 1, len(raw_blobs)):
                b2 = raw_blobs[j]
                
                # Bounded lookahead
                if b2['gy'] - (b1['gy'] + b1['gh']) > merge_dy:
                    break
                if b2['gx'] > b1['gx'] + b1['gw'] + merge_dx * 3 or b2['gx'] + b2['gw'] < b1['gx'] - merge_dx * 3:
                    continue
                    
                dx = max(0, max(b1['gx'], b2['gx']) - min(b1['gx']+b1['gw'], b2['gx']+b2['gw']))
                dy = max(0, max(b1['gy'], b2['gy']) - min(b1['gy']+b1['gh'], b2['gy']+b2['gh']))
                
                if dx <= merge_dx and dy <= merge_dy:
                    union(i, j)
                    
        grouped = {}
        for i, b in enumerate(raw_blobs):
            root = find(i)
            if root not in grouped:
                grouped[root] = {'gx': b['gx'], 'gy': b['gy'], 'r': b['gx']+b['gw'], 'b': b['gy']+b['gh'], 'cells': b['cells']}
            else:
                gb = grouped[root]
                gb['gx'] = min(gb['gx'], b['gx'])
                gb['gy'] = min(gb['gy'], b['gy'])
                gb['r'] = max(gb['r'], b['gx']+b['gw'])
                gb['b'] = max(gb['b'], b['gy']+b['gh'])
                gb['cells'] += b['cells']
                
        blobs = []
        for gb in grouped.values():
            blobs.append({
                'gx': gb['gx'], 'gy': gb['gy'], 
                'gw': gb['r'] - gb['gx'], 'gh': gb['b'] - gb['gy'],
                'cells': gb['cells']
            })
            
        regions = []
        region_id = 1
        
        for b in blobs:
            rx = b['gx'] * grid_size
            ry = b['gy'] * grid_size
            rw = b['gw'] * grid_size
            rh = b['gh'] * grid_size
            
            # Explicit image boundary clamping
            rx = max(0, min(rx, w - 1))
            ry = max(0, min(ry, h - 1))
            if rx + rw > w: rw = w - rx
            if ry + rh > h: rh = h - ry
            
            # Minimum region size filter (discard tiny character noise < 16 px area)
            if rw <= 0 or rh <= 0 or (rw * rh) < 16:
                continue
                
            box_area = b['gw'] * b['gh']
            likelihood = b['cells'] / box_area if box_area > 0 else 0.0
            likelihood = max(0.0, min(1.0, likelihood))
            
            kind = "text_candidate"
            if likelihood > 0.85 and (b['gw'] > 30 and b['gh'] <= 2):
                kind = "non_text_candidate" # Long horizontal line rule
            elif likelihood > 0.85 and (b['gh'] > 30 and b['gw'] <= 2):
                kind = "non_text_candidate" # Long vertical line rule
            elif likelihood < 0.20 and box_area > 60:
                kind = "unknown_candidate"   # Sparse stamp/signature candidate
                
            regions.append({
                "region_id": region_id,
                "x": int(rx),
                "y": int(ry),
                "width": int(rw),
                "height": int(rh),
                "content_likelihood": round(likelihood, 3),
                "region_kind": kind
            })
            region_id += 1
            
        del pix
        
        return {
            "analysis_successful": True,
            "width": w,
            "height": h,
            "regions": regions
        }
        
    except Exception as e:
        return {"analysis_successful": False, "error": str(e)}
