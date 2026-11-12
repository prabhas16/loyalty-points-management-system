-- MySQL dump 10.13  Distrib 8.0.46, for Win64 (x86_64)
--
-- Host: 127.0.0.1    Database: loyalty_db
-- ------------------------------------------------------
-- Server version	26.7.0

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
SET @MYSQLDUMP_TEMP_LOG_BIN = @@SESSION.SQL_LOG_BIN;
SET @@SESSION.SQL_LOG_BIN= 0;

--
-- GTID state at the beginning of the backup 
--

SET @@GLOBAL.GTID_PURGED=/*!80000 '+'*/ 'a0f45464-a51b-11f1-9558-d843ae0a2e3f:1-442';

--
-- Table structure for table `redemption`
--

DROP TABLE IF EXISTS `redemption`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `redemption` (
  `redemption_id` varchar(30) NOT NULL,
  `account_id` varchar(30) NOT NULL,
  `reward_id` varchar(20) NOT NULL,
  `points_spent` bigint NOT NULL,
  `redemption_date` datetime NOT NULL,
  `status` enum('APPROVED','REJECTED','CANCELLED') NOT NULL,
  PRIMARY KEY (`redemption_id`),
  KEY `account_id` (`account_id`),
  KEY `reward_id` (`reward_id`),
  CONSTRAINT `redemption_ibfk_1` FOREIGN KEY (`account_id`) REFERENCES `loyaltyaccount` (`account_id`),
  CONSTRAINT `redemption_ibfk_2` FOREIGN KEY (`reward_id`) REFERENCES `reward` (`reward_id`),
  CONSTRAINT `redemption_chk_1` CHECK ((`points_spent` > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `redemption`
--

LOCK TABLES `redemption` WRITE;
/*!40000 ALTER TABLE `redemption` DISABLE KEYS */;
INSERT INTO `redemption` VALUES ('RDM-2026-100001','LOY-000203','RW-001',43197,'2024-01-01 00:00:00','APPROVED');
/*!40000 ALTER TABLE `redemption` ENABLE KEYS */;
UNLOCK TABLES;
SET @@SESSION.SQL_LOG_BIN = @MYSQLDUMP_TEMP_LOG_BIN;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-11-12 22:15:14
