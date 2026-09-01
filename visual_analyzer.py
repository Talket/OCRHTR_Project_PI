import os
import pymupdf
from typing import Dict, Any
from collections import defaultdict

def analyze_page_image(image_path: str) -> Dict[str, Any]:
    """
    Lightweight, CPU-friendly bounded 2D visual region analyzer optimized for Raspberry Pi 3B.
    
    1. 4x4 Grid Sampling
    2. Long Rule Extraction & Grid Stripping (prevents structural bridging)
    3. Horizontal Smearing (local word/line grouping)
    4. Augmented Union-Find Vertical Linking (enforces 50% X-overlap & 400px height cap)
    """
    if not os.path.exists(image_path):
        return {"analysis_successful": False, "error": f"Image not found: {image_path}"}
        
    try:
        pix = pymupdf.Pixmap(image_path)
        w, h = pix.width, pix.height
        n_components = pix.n
        samples = pix.samples
        
        # 1. Image Sampling (4x4 Grid for high line precision)
        grid_size = 4
        gw = w // grid_size
        gh = h // grid_size
        
        # 1D array representing the 2D grid: ink_grid[y * gw + x]
        ink_grid = [False] * (gw * gh)
        
        # 4-point check inside each 4x4 cell to prevent thin stroke misses
        offsets = [(0, 0), (2, 0), (0, 2), (2, 2)]
        
        for cy in range(gh):
            for cx in range(gw):
                px_base = cx * grid_size
                py_base = cy * grid_size
                is_ink = False
                
                for dx, dy in offsets:
                    px = px_base + dx
                    py = py_base + dy
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
                    ink_grid[cy * gw + cx] = True
                    
        # 2. Extract Long Lines (Rules/Borders) to prevent structural text bridging
        h_lines = []
        v_lines = []
        
        # Detect Horizontal Lines (> 100px / 25 cells)
        for cy in range(gh):
            run = 0
            for cx in range(gw):
                if ink_grid[cy * gw + cx]:
                    run += 1
                else:
                    if run >= 25: 
                        h_lines.append((cx - run, cy, run, 1))
                    run = 0
            if run >= 25: 
                h_lines.append((gw - run, cy, run, 1))
                
        # Detect Vertical Lines (> 100px / 25 cells)
        for cx in range(gw):
            run = 0
            for cy in range(gh):
                if ink_grid[cy * gw + cx]:
                    run += 1
                else:
                    if run >= 25: 
                        v_lines.append((cx, cy - run, 1, run))
                    run = 0
            if run >= 25: 
                v_lines.append((cx, gh - run, 1, run))
                
        raw_blocks = []
        
        # Output lines as non_text regions and REMOVE them from the ink grid
        for lx, ly, lw, lh in h_lines:
            raw_blocks.append({'gx': lx, 'gy': ly, 'gw': lw, 'gh': lh, 'cells': lw*lh, 'type': 'non_text_candidate'})
            for cx in range(lx, lx + lw): 
                ink_grid[ly * gw + cx] = False
                
        for lx, ly, lw, lh in v_lines:
            raw_blocks.append({'gx': lx, 'gy': ly, 'gw': lw, 'gh': lh, 'cells': lw*lh, 'type': 'non_text_candidate'})
            for cy in range(ly, ly + lh): 
                ink_grid[cy * gw + lx] = False

        # 3. Horizontal Smearing -> Segments (Group characters/words into row-bound segments)
        segments = []
        max_h_gap = 3 # 12px horizontal tolerance (keeps columns split)
        
        for cy in range(gh):
            current_seg = None
            gap = 0
            for cx in range(gw):
                if ink_grid[cy * gw + cx]:
                    if current_seg is None:
                        current_seg = [cy, cx, cx, 1] # [y, x_start, x_end, cells]
                    else:
                        current_seg[2] = cx
                        current_seg[3] += 1
                    gap = 0
                else:
                    if current_seg is not None:
                        gap += 1
                        if gap > max_h_gap:
                            segments.append(current_seg)
                            current_seg = None
            if current_seg is not None:
                segments.append(current_seg)

        # 4. Vertical Component Linking (Augmented Union-Find)
        parent = list(range(len(segments)))
        dsu_min_y = [seg[0] for seg in segments]
        dsu_max_y = [seg[0] for seg in segments]
        
        # 400px maximum height for grouped text blocks to prevent runaway chains
        MAX_BLOCK_HEIGHT_CELLS = 100 
        
        def find(i):
            if parent[i] == i: return i
            parent[i] = find(parent[i])
            return parent[i]
            
        def union(i, j):
            root_i = find(i)
            root_j = find(j)
            if root_i != root_j:
                new_min = min(dsu_min_y[root_i], dsu_min_y[root_j])
                new_max = max(dsu_max_y[root_i], dsu_max_y[root_j])
                # Refuse merge if resulting block exceeds height cap
                if (new_max - new_min + 1) > MAX_BLOCK_HEIGHT_CELLS:
                    return
                parent[root_i] = root_j
                dsu_min_y[root_j] = new_min
                dsu_max_y[root_j] = new_max
                
        # Group segments by Y for fast adjacent row lookups
        segments_by_y = defaultdict(list)
        for i, seg in enumerate(segments):
            segments_by_y[seg[0]].append((i, seg))
            
        # Connect segments across adjacent rows ONLY if they share substantial X-overlap
        for cy in range(gh):
            if cy not in segments_by_y: continue
            
            # Lookahead up to 2 rows (8px vertical gap)
            for offset in (1, 2):
                ny = cy + offset
                if ny in segments_by_y:
                    for i, s1 in segments_by_y[cy]:
                        s1_w = s1[2] - s1[1] + 1
                        for j, s2 in segments_by_y[ny]:
                            s2_w = s2[2] - s2[1] + 1
                            
                            # Calculate intersection span
                            overlap = max(0, min(s1[2], s2[2]) - max(s1[1], s2[1]) + 1)
                            
                            # Strict condition: Overlap must be >= 50% of the smaller segment's width.
                            # Protects against thin diagonal noise connecting adjacent columns.
                            if overlap >= 0.5 * min(s1_w, s2_w):
                                union(i, j)
                                
        # 5. Extract Text Blocks
        groups = defaultdict(list)
        for i, seg in enumerate(segments):
            groups[find(i)].append(seg)
            
        for g_id, segs in groups.items():
            min_x = min(s[1] for s in segs)
            max_x = max(s[2] for s in segs)
            min_y = min(s[0] for s in segs)
            max_y = max(s[0] for s in segs)
            cells = sum(s[3] for s in segs)
            
            raw_blocks.append({
                'gx': min_x, 'gy': min_y,
                'gw': max_x - min_x + 1,
                'gh': max_y - min_y + 1,
                'cells': cells,
                'type': 'text_candidate'
            })
            
        # 6. Apply Absolute Dimensional Constraints
        constrained_blocks = []
        for b in raw_blocks:
            # Solid noise massive regions -> Flag as unknown for evidence preservation
            if (b['gw'] * grid_size > w * 0.5) and (b['gh'] * grid_size > h * 0.5):
                b['type'] = 'unknown_candidate'
            constrained_blocks.append(b)

        # 7. Result Formatting & Filtering
        regions = []
        region_id = 1
        
        for b in constrained_blocks:
            rx = b['gx'] * grid_size
            ry = b['gy'] * grid_size
            rw = b['gw'] * grid_size
            rh = b['gh'] * grid_size
            
            # Strict image boundary clamping
            rx = max(0, min(rx, w - 1))
            ry = max(0, min(ry, h - 1))
            rw = max(1, min(rw, w - rx))
            rh = max(1, min(rh, h - ry))
            
            # Minimum region size filter (discard tiny noise area < 16px)
            if rw <= 0 or rh <= 0 or (rw * rh) < 16:
                continue
                
            # Filter page-edge binding artifacts (strip width < 16 on extreme borders)
            if b['type'] == 'text_candidate' and rw < 16 and (rx < 16 or (rx + rw) > w - 16):
                continue
                
            box_area = b['gw'] * b['gh']
            likelihood = b['cells'] / box_area if box_area > 0 else 0.0
            likelihood = max(0.0, min(1.0, likelihood))
            
            kind = b['type']
            if likelihood < 0.20 and box_area > 50 and kind == 'text_candidate':
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
