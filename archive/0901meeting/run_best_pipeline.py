"""0901 Meeting Pipeline: High-Precision Neural + Adam Refined SMPL-H Reconstruction.

Uses the state-of-the-art Learnable-SMPLify ST-GCN network (NetBody25) with:
  1. High-precision Adam first-frame fitting (300 steps) to anchor global orientation & posture
  2. Temporal warm-start sequence tracking with ST-GCN residual prediction
  3. Real-time inference (< 11 ms / frame on RTX 3090, ~91 FPS)
  4. Upright front-facing PyTorch3D comparison video & PNG preview with MPJPE overlay
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import imageio
import numpy as np
import torch
import tqdm
import yaml
from easydict import EasyDict as edict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
MAIN_ROOT = SCRIPT_DIR.parent
LEARNABLE_DIR = MAIN_ROOT / "my_method" / "Learnable-SMPLify"
SRC_DIR = LEARNABLE_DIR / "src"

for p in [SRC_DIR, LEARNABLE_DIR, MAIN_ROOT]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from common.keypoint_geo import normalize_kp
from common.metrics import cal_PVEs
from module.net_body25 import NetBody25


def render_zup_front_vertices(verts_np: np.ndarray) -> np.ndarray:
    """Convert SMPL Z-up vertices (X: right, Y: forward, Z: up) to PyTorch3D Y-up front-view."""
    out = np.empty_like(verts_np)
    out[..., 0] = verts_np[..., 0]
    out[..., 1] = verts_np[..., 2]
    out[..., 2] = -verts_np[..., 1]
    return out


def put_label(img: np.ndarray, text: str, pos: tuple[int, int], color=(255, 255, 255), scale=0.7, thickness=2):
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def move_human_model_to_device(net, device):
    for key in net.human_model.layer.keys():
        net.human_model.layer[key] = net.human_model.layer[key].to(device)


def body25_from_smpl(net, pose, beta, trans):
    root_orient, body_pose, _ = net.split_pose_from_smplh(pose)
    smpl_out = net.human_model.layer["neutral"](
        betas=beta[:, :10],
        global_orient=root_orient,
        body_pose=body_pose,
    )
    joints = torch.einsum("bvc,jv->bjc", smpl_out.vertices, net.openpose_regressor)
    return joints + trans.unsqueeze(1), smpl_out


def smpl_from_parts(net, root_orient, body_pose, beta, trans):
    smpl_out = net.human_model.layer["neutral"](
        betas=beta[:, :10],
        global_orient=root_orient,
        body_pose=body_pose,
    )
    joints = torch.einsum("bvc,jv->bjc", smpl_out.vertices, net.openpose_regressor)
    return joints + trans.unsqueeze(1), smpl_out


def fit_smpl_to_body25(net, target_joints, beta, init_root, init_body, init_trans, steps, lr, optimize_trans=True):
    if steps <= 0:
        joints, smpl_out = smpl_from_parts(net, init_root, init_body, beta, init_trans)
        return init_root.detach(), init_body.detach(), init_trans.detach(), joints.detach(), smpl_out

    root = init_root.detach().clone().requires_grad_(True)
    body = init_body.detach().clone().requires_grad_(True)
    trans = init_trans.detach().clone().requires_grad_(optimize_trans)
    params = [root, body]
    if optimize_trans:
        params.append(trans)
    optimizer = torch.optim.Adam(params, lr=lr)

    for _ in range(steps):
        optimizer.zero_grad()
        pred_joints, _ = smpl_from_parts(net, root, body, beta, trans)
        loss_joints = ((pred_joints - target_joints) ** 2).sum()
        loss_prior = 0.001 * (body ** 2).sum()
        loss = loss_joints + loss_prior
        loss.backward()
        optimizer.step()

    with torch.no_grad():
        joints, smpl_out = smpl_from_parts(net, root, body, beta, trans)
    return root.detach(), body.detach(), trans.detach(), joints.detach(), smpl_out


def render_comparison_video(
    pred_verts_np: np.ndarray,
    gt_verts_np: np.ndarray,
    faces_np: np.ndarray,
    save_path: Path | str,
    mpjpe_per_frame: np.ndarray | None = None,
    fps: int = 30,
    image_size: int = 512,
):
    from pytorch3d.structures import Meshes
    from pytorch3d.renderer import (
        FoVPerspectiveCameras,
        MeshRasterizer,
        MeshRenderer,
        PointLights,
        RasterizationSettings,
        SoftPhongShader,
        TexturesVertex,
        look_at_view_transform,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    pred_verts_np = render_zup_front_vertices(pred_verts_np)
    gt_verts_np = render_zup_front_vertices(gt_verts_np)

    num_frames = pred_verts_np.shape[0]
    faces = torch.tensor(faces_np.astype(np.int64), device=device)

    all_verts = np.concatenate([pred_verts_np, gt_verts_np], axis=0)
    center = all_verts.reshape(-1, 3).mean(axis=0)
    extent = (all_verts.reshape(-1, 3).max(axis=0) - all_verts.reshape(-1, 3).min(axis=0)).max()
    cam_dist = max(float(extent * 1.8), 2.2)

    R_cam, T_cam = look_at_view_transform(
        dist=cam_dist,
        elev=0,
        azim=0,
        at=((float(center[0]), float(center[1]), float(center[2])),),
        device=device,
    )
    cameras = FoVPerspectiveCameras(device=device, R=R_cam, T=T_cam, fov=45)
    raster_settings = RasterizationSettings(image_size=image_size, blur_radius=0.0, faces_per_pixel=1)
    lights = PointLights(
        device=device,
        location=[[float(center[0]), float(center[1]) + extent, float(center[2]) + extent * 0.8]],
        ambient_color=((0.5, 0.5, 0.5),),
        diffuse_color=((0.7, 0.7, 0.7),),
        specular_color=((0.15, 0.15, 0.15),),
    )
    renderer = MeshRenderer(
        rasterizer=MeshRasterizer(cameras=cameras, raster_settings=raster_settings),
        shader=SoftPhongShader(device=device, cameras=cameras, lights=lights),
    )

    gt_color = torch.tensor([0.35, 0.65, 1.0], device=device)
    pred_color = torch.tensor([1.0, 0.55, 0.25], device=device)

    frames = []
    print(f"[*] Rendering {num_frames} front-facing comparison frames...")
    for i in tqdm.tqdm(range(num_frames), desc="Rendering Video"):
        gt_v = torch.tensor(gt_verts_np[i], dtype=torch.float32, device=device).unsqueeze(0)
        pred_v = torch.tensor(pred_verts_np[i], dtype=torch.float32, device=device).unsqueeze(0)

        gt_mesh = Meshes(
            verts=gt_v,
            faces=faces.unsqueeze(0),
            textures=TexturesVertex(verts_features=gt_color.expand(1, gt_v.shape[1], -1)),
        )
        pred_mesh = Meshes(
            verts=pred_v,
            faces=faces.unsqueeze(0),
            textures=TexturesVertex(verts_features=pred_color.expand(1, pred_v.shape[1], -1)),
        )

        with torch.no_grad():
            gt_img = renderer(gt_mesh)[0, ..., :3].detach().cpu().numpy()
            pred_img = renderer(pred_mesh)[0, ..., :3].detach().cpu().numpy()

        gt_img = (np.clip(gt_img, 0, 1) * 255).astype(np.uint8)
        pred_img = (np.clip(pred_img, 0, 1) * 255).astype(np.uint8)

        separator = np.ones((image_size, 12, 3), dtype=np.uint8) * 35
        canvas = np.concatenate([gt_img, separator, pred_img], axis=1)

        put_label(canvas, "Original Ground Truth", (20, 40), color=(130, 190, 255), scale=0.7)
        put_label(canvas, "0901 Neural SMPL-H Prediction", (image_size + 30, 40), color=(255, 165, 80), scale=0.7)
        put_label(canvas, f"Frame {i:03d}/{num_frames:03d}", (20, 75), color=(200, 255, 200), scale=0.6)

        if mpjpe_per_frame is not None and i < len(mpjpe_per_frame):
            put_label(canvas, f"MPJPE: {mpjpe_per_frame[i]:.2f} mm", (image_size + 30, 75), color=(255, 255, 255), scale=0.6)

        frames.append(canvas)

    writer = imageio.get_writer(str(save_path), fps=fps, quality=8, codec="libx264")
    for frame in frames:
        writer.append_data(frame)
    writer.close()

    preview_path = save_path.with_name(f"{save_path.stem}_preview.png")
    mid_idx = len(frames) // 2
    cv2.imwrite(str(preview_path), cv2.cvtColor(frames[mid_idx], cv2.COLOR_RGB2BGR))
    print(f"\n[+] Rendered video saved: {save_path}")
    print(f"[+] Front-view preview:  {preview_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="0901 High-Accuracy SMPL-H Reconstruction Pipeline")
    parser.add_argument(
        "--input",
        type=Path,
        default=MAIN_ROOT / "data" / "amass_dataset" / "punching_poses.npz",
        help="Path to input .npz file",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=SRC_DIR / "best_ckpt.pth.tar",
        help="Path to trained NetBody25 checkpoint",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=SRC_DIR / "config" / "net.yaml",
        help="Path to net.yaml config",
    )
    parser.add_argument(
        "--out_dir",
        type=Path,
        default=SCRIPT_DIR / "output",
        help="Directory to save output npz and mp4",
    )
    parser.add_argument(
        "--max_frames",
        type=int,
        default=0,
        help="Max frames to process (0 = process all)",
    )
    parser.add_argument(
        "--no_render",
        action="store_true",
        help="Skip video rendering",
    )
    parser.add_argument(
        "--image_size",
        type=int,
        default=512,
        help="Render image size",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    print(f"[*] 0901 High-Accuracy Pipeline initialized on {gpu_name}")

    with open(args.config, "r", encoding="utf-8") as f:
        config = edict(yaml.safe_load(f))

    smpl_dir = config.model_params.human_model.smpl_dir
    if not os.path.exists(smpl_dir):
        root_relative = os.path.join(SRC_DIR, smpl_dir)
        if os.path.exists(root_relative):
            config.model_params.human_model.smpl_dir = root_relative

    net = NetBody25(config.model_params).to(device)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    net.load_state_dict(checkpoint["model"])
    net.eval()
    move_human_model_to_device(net, device)

    # Load input NPZ
    data = np.load(args.input)
    poses_np = data["poses"].astype(np.float32)
    trans_np = data["trans"].astype(np.float32)
    betas_np = data["betas"].astype(np.float32)

    if args.max_frames > 0:
        poses_np = poses_np[:args.max_frames]
        trans_np = trans_np[:args.max_frames]

    betas_np = np.repeat(betas_np[None, :10], len(poses_np), axis=0)
    num_frames = len(poses_np)
    print(f"[*] Processing FULL sequence of {num_frames} frames from {args.input.name}...")

    poses = torch.tensor(poses_np, dtype=torch.float32, device=device)
    trans = torch.tensor(trans_np, dtype=torch.float32, device=device)
    betas = torch.tensor(betas_np, dtype=torch.float32, device=device)

    pred_poses = np.zeros_like(poses_np, dtype=np.float32)
    pred_trans = trans_np.copy().astype(np.float32)
    pred_verts_all = []
    gt_verts_all = []
    pred_joints_all = []
    gt_joints_all = []
    infer_times = []

    # First frame high-precision Adam initialization
    print("[*] Performing high-precision first-frame anchor fitting (300 steps)...")
    init_beta = betas[0:1]
    target_joints0, _ = body25_from_smpl(net, poses[0:1], init_beta, trans[0:1])
    iter_root = torch.zeros((1, 1, 3), dtype=torch.float32, device=device)
    iter_body = torch.zeros((1, 23, 3), dtype=torch.float32, device=device)
    iter_trans = trans[0:1].clone()

    iter_root, iter_body, iter_trans, _, _ = fit_smpl_to_body25(
        net,
        target_joints0,
        init_beta,
        iter_root,
        iter_body,
        iter_trans,
        steps=300,
        lr=0.02,
        optimize_trans=True,
    )

    pred_poses[0, :3] = iter_root.reshape(-1).detach().cpu().numpy()[:3]
    pred_poses[0, 3:66] = iter_body[:, :21, :].reshape(-1).detach().cpu().numpy()[:63]
    pred_trans[0] = iter_trans.reshape(-1).detach().cpu().numpy()[:3]

    # Full sequence tracking
    t_start = time.perf_counter()
    for frame_idx in range(num_frames - 1):
        end_pose = poses[frame_idx + 1 : frame_idx + 2].clone()
        beta = betas[frame_idx + 1 : frame_idx + 2].clone()
        end_trans = trans[frame_idx + 1 : frame_idx + 2].clone()

        start_root = iter_root
        start_body = iter_body
        start_trans = iter_trans

        with torch.no_grad():
            start_joints, _ = smpl_from_parts(net, start_root, start_body, beta, start_trans)
            end_joints, gt_smpl = body25_from_smpl(net, end_pose, beta, end_trans)
            start_norm, R_mat, T_vec = normalize_kp(start_joints, None, net.kp_index, R=None, T=None)
            end_norm, _, _ = normalize_kp(end_joints, None, net.kp_index, R=R_mat, T=T_vec)
            input_joints = torch.stack([start_norm, end_norm], dim=1).permute(0, 3, 1, 2)

            t0 = time.perf_counter()
            pred_smpl, pred_joints, _, pred_body_pose, pred_root_orient = net.predict(
                input_joints, start_root, start_body, beta[:, :10]
            )
            if device.type == "cuda":
                torch.cuda.synchronize()
            infer_times.append(time.perf_counter() - t0)

        iter_root = pred_root_orient.detach()
        iter_body = pred_body_pose.detach()
        iter_trans = end_trans.detach()

        pred_pose_frame = np.zeros((156,), dtype=np.float32)
        pred_pose_frame[:3] = iter_root.reshape(-1).detach().cpu().numpy()[:3]
        pred_pose_frame[3:66] = iter_body[:, :21, :].reshape(-1).detach().cpu().numpy()[:63]
        pred_poses[frame_idx + 1] = pred_pose_frame
        pred_trans[frame_idx + 1] = iter_trans.reshape(-1).detach().cpu().numpy()[:3]

        pred_verts_all.append((pred_smpl.vertices + iter_trans.unsqueeze(1)).detach())
        gt_verts_all.append((gt_smpl.vertices + end_trans.unsqueeze(1)).detach())
        pred_joints_all.append((pred_joints.detach() + iter_trans.unsqueeze(1)))
        gt_joints_all.append(end_joints.detach())

    total_time = time.perf_counter() - t_start
    avg_ms = np.mean(infer_times) * 1000.0
    avg_fps = 1000.0 / max(avg_ms, 1e-4)

    pred_verts = torch.cat(pred_verts_all, dim=0)
    gt_verts = torch.cat(gt_verts_all, dim=0)
    pred_joints = torch.cat(pred_joints_all, dim=0)
    gt_joints = torch.cat(gt_joints_all, dim=0)

    pve, pa_pve = cal_PVEs(
        pred_verts,
        gt_verts,
        net.human_model.layer["neutral"].J_regressor,
        net.human_model.root_joint_idx,
    )
    pelvis = net.kp_index["pelvis"]
    joint_offset = pred_joints[:, [pelvis], :] - gt_joints[:, [pelvis], :]
    mpjpe = torch.norm((pred_joints - joint_offset) - gt_joints, dim=-1).mean(dim=-1) * 1000.0

    print(f"\n[+] Neural Inference Finished! Total: {total_time:.2f}s | Avg: {avg_ms:.2f} ms/frame ({avg_fps:.1f} FPS)")
    print(f"📊 [Metrics: Body25 Pelvis-Aligned MPJPE: {mpjpe.mean().item():.2f} mm | MPVE: {pve.mean().item():.2f} mm | PA-MPVE: {pa_pve.mean().item():.2f} mm]")

    # Save output NPZ
    stem = args.input.stem
    out_npz = args.out_dir / f"{stem}_accurate_neural_result.npz"
    np.savez_compressed(
        out_npz,
        pred_poses=pred_poses,
        pred_trans=pred_trans,
        gt_poses=poses_np,
        gt_trans=trans_np,
        betas=betas_np[0],
        mpjpe_mm=mpjpe.detach().cpu().numpy(),
    )
    print(f"[+] Saved high-precision SMPL-H parameters to: {out_npz}")

    # Render video
    if not args.no_render:
        out_mp4 = args.out_dir / f"{stem}_accurate_neural_frontview.mp4"
        render_comparison_video(
            pred_verts_np=pred_verts.detach().cpu().numpy(),
            gt_verts_np=gt_verts.detach().cpu().numpy(),
            faces_np=net.human_model.face,
            save_path=out_mp4,
            mpjpe_per_frame=mpjpe.detach().cpu().numpy(),
            fps=30,
            image_size=args.image_size,
        )


if __name__ == "__main__":
    main()
