# calibration
lerobot-calibrate --robot.type=so101_follower --robot.port=COM24 --robot.id=fenghao_so101_follower
lerobot-calibrate --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=fenghao_so101_leader

# teleoperate without camera
lerobot-teleoperate `
  --robot.type=so101_follower --robot.port=COM24 --robot.id=fenghao_so101_follower `
  --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=fenghao_so101_leader


# teleoperate with camera
lerobot-find-cameras opencv

lerobot-teleoperate `
  --robot.type=so101_follower --robot.port=COM24 --robot.id=fenghao_so101_follower `
  --robot.cameras="{ fixed: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 15}, wrist: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 15}}" `
  --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=fenghao_so101_leader `
  --display_data=false

lerobot-teleoperate `
  --robot.type=so101_follower --robot.port=COM24 --robot.id=fenghao_so101_follower `
  --robot.cameras="{fixed: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 15}}" `
  --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=fenghao_so101_leader `
  --display_data=true


# smoke_test
lerobot-record `
  --robot.type=so101_follower --robot.port=COM24 --robot.id=fenghao_so101_follower `
  --robot.cameras="{ wrist: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 15}, fixed: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 15}}" `
  --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=fenghao_so101_leader `
  --display_data=false `
  --dataset.repo_id=fenghao/so101_smoke_test `
  --dataset.num_episodes=2 `
  --dataset.single_task="move the gripper near the object" `
  --dataset.push_to_hub=False
